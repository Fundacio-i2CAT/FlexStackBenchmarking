// SPDX-License-Identifier: AGPL-3.0-only
// Vanetza benchmark harness (WP-D): the modes, options, CAM content and CSV
// schema of the FlexStack harnesses (../rust/src/main.rs, ../python/benchmark.py)
// on Vanetza (https://github.com/riebl/vanetza, pinned commit, see README.md).
//
// Modes:
//   codec-encode / codec-decode  UPER encode / decode of the release-2 CAM
//                                (TS 103 900 V2.3.1, Vanetza's asn1c bindings)
//   security-sign / -verify      SN-ENCAP / SN-DECAP of the encoded CAM through
//                                Vanetza's security entity (TS 103 097, v3,
//                                CAM sign policy), the entity its router uses
//   tx                           CAM encode -> BTP-B -> GeoNetworking SHB ->
//                                (sign) -> raw Ethernet socket, per packet,
//                                synchronous (Vanetza's send path is one thread)
//   rx                           CAMs from a remote sender: frame received ->
//                                GN -> (verify) -> BTP -> CAM decoded
//
// Everything Vanetza-specific is built on socktap's sources (link layer,
// positioning, security set-up), unchanged.

#include "dcc_passthrough.hpp"
#include "ethernet_device.hpp"
#include "link_layer.hpp"
#include "positioning.hpp"
#include "security.hpp"
#include "time_trigger.hpp"

#include <vanetza/access/ethertype.hpp>
#include <vanetza/asn1/cam.hpp>
#include <vanetza/asn1/packet_visitor.hpp>
#include <vanetza/btp/port_dispatcher.hpp>
#include <vanetza/btp/header.hpp>
#include <vanetza/btp/header_conversion.hpp>
#include <vanetza/geonet/data_confirm.hpp>
#include <vanetza/btp/ports.hpp>
#include <vanetza/common/byte_order.hpp>
#include <vanetza/units/time.hpp>
#include <vanetza/common/its_aid.hpp>
#include <vanetza/geonet/router.hpp>
#include <vanetza/security/decap_service.hpp>
#include <vanetza/security/encap_service.hpp>
#include <vanetza/security/security_entity.hpp>
#include <vanetza/security/sign_service.hpp>
#include <vanetza/security/v3/secured_message.hpp>

#include <boost/asio/io_context.hpp>
#include <boost/program_options.hpp>
#include <boost/variant/get.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <numeric>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace po = boost::program_options;
using namespace vanetza;
using SteadyClock = std::chrono::steady_clock;

static const char* CSV_HEADER =
    "run_id,implementation,platform,security,benchmark,duration_s,total_cams,throughput_cams_s,"
    "latency_mean_us,latency_std_us,latency_p50_us,latency_p95_us,latency_p99_us,latency_min_us,"
    "latency_max_us,sign_latency_mean_us,cpu_pct,rss_start_mb,peak_rss_mb,target_rate";

// ── Resources: the definitions of ../rust/src/resources.rs ───────────────────
struct Resources { double cpu_pct = NAN, rss_start_mb = NAN, peak_rss_mb = NAN; };

static long status_kb(const std::string& key)
{
    std::ifstream in("/proc/self/status");
    std::string line;
    while (std::getline(in, line)) {
        if (line.compare(0, key.size(), key) == 0) {
            return std::stol(line.substr(key.size()));
        }
    }
    return -1;
}

static long cpu_ticks()
{
    std::ifstream in("/proc/self/stat");
    std::string stat((std::istreambuf_iterator<char>(in)), {});
    auto close = stat.rfind(')');
    if (close == std::string::npos) return -1;
    std::istringstream rest(stat.substr(close + 1));
    std::string field;
    long utime = -1, stime = -1;
    for (int i = 0; rest >> field; ++i) {
        if (i == 11) utime = std::stol(field);
        if (i == 12) { stime = std::stol(field); break; }
    }
    return (utime < 0 || stime < 0) ? -1 : utime + stime;
}

struct ResourceSnapshot {
    long ticks = cpu_ticks();
    SteadyClock::time_point wall = SteadyClock::now();
    long rss_kb = status_kb("VmRSS:");

    Resources finish() const
    {
        Resources r;
        double wall_s = std::chrono::duration<double>(SteadyClock::now() - wall).count();
        long now = cpu_ticks();
        if (ticks >= 0 && now >= 0 && wall_s > 0) {
            r.cpu_pct = (now - ticks) / 100.0 / wall_s * 100.0; // USER_HZ = 100
        }
        if (rss_kb >= 0) r.rss_start_mb = rss_kb / 1024.0;
        long hwm = status_kb("VmHWM:");
        if (hwm >= 0) r.peak_rss_mb = hwm / 1024.0;
        return r;
    }
};

// ── Pacing: the absolute schedule of ../rust/src/pacing.rs ───────────────────
struct Pacer {
    bool enabled;
    SteadyClock::time_point start;
    std::chrono::duration<double> interval;
    unsigned long next = 0, late = 0;

    Pacer(double rate, SteadyClock::time_point s) :
        enabled(std::isfinite(rate) && rate > 0), start(s),
        interval(enabled ? 1.0 / rate : 0.0) {}

    bool wait(SteadyClock::time_point end)
    {
        if (!enabled) return true;
        auto release = start + std::chrono::duration_cast<SteadyClock::duration>(interval * double(next));
        if (release >= end) return false;
        ++next;
        auto now = SteadyClock::now();
        if (release > now) {
            std::this_thread::sleep_for(release - now);
        } else if (next > 1) {
            ++late;
        }
        return true;
    }
};

// ── Statistics: mean, sample std, rounded-index percentile (as the Rust harness) ──
struct Stats { double mean = 0, std = 0, p50 = 0, p95 = 0, p99 = 0, min = 0, max = 0; };

static Stats stats(std::vector<double>& v)
{
    Stats s;
    if (v.empty()) return s;
    std::sort(v.begin(), v.end());
    s.mean = std::accumulate(v.begin(), v.end(), 0.0) / v.size();
    if (v.size() > 1) {
        double acc = 0;
        for (double x : v) acc += (x - s.mean) * (x - s.mean);
        s.std = std::sqrt(acc / (v.size() - 1));
    }
    auto pct = [&](double p) { return v[std::min<std::size_t>(std::lround(p / 100.0 * (v.size() - 1)), v.size() - 1)]; };
    s.p50 = pct(50); s.p95 = pct(95); s.p99 = pct(99);
    s.min = v.front(); s.max = v.back();
    return s;
}

static double mean(const std::vector<double>& v)
{
    return v.empty() ? 0.0 : std::accumulate(v.begin(), v.end(), 0.0) / v.size();
}

struct Args {
    std::string mode, security, output, run_id, platform, interface, certs_dir, backend;
    unsigned duration = 60, warmup = 5, at = 1;
    double rate = 0;
};

static void write_row(const Args& a, const std::string& security, double elapsed, std::size_t total,
                      std::vector<double>& lat, double sign_mean, const Resources& r)
{
    Stats s = stats(lat);
    bool exists = std::ifstream(a.output).good();
    if (exists) {
        std::ifstream in(a.output);
        std::string first;
        std::getline(in, first);
        if (!first.empty() && first != CSV_HEADER) {
            std::cerr << "ERROR: " << a.output << " has a different CSV header (older schema?). Use a new output file.\n";
            std::exit(2);
        }
    }
    std::ofstream out(a.output, std::ios::app);
    if (!exists) out << CSV_HEADER << "\n";
    std::ostringstream rate;
    rate << a.rate;
    char row[1024];
    std::snprintf(row, sizeof(row),
        "%s,vanetza,%s,%s,%s,%.3f,%zu,%.1f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.1f,%.2f,%.2f,%s",
        a.run_id.c_str(), a.platform.c_str(), security.c_str(), a.mode.c_str(), elapsed, total,
        total / elapsed, s.mean, s.std, s.p50, s.p95, s.p99, s.min, s.max, sign_mean,
        r.cpu_pct, r.rss_start_mb, r.peak_rss_mb, rate.str().c_str());
    out << row << "\n";
    std::printf("    Throughput   : %.1f CAMs/s\n    Latency p50  : %.2f us\n    CPU          : %.1f %%\n",
                total / elapsed, s.p50, r.cpu_pct);
}

static double us_since(SteadyClock::time_point t0)
{
    return std::chrono::duration<double, std::micro>(SteadyClock::now() - t0).count();
}

// ── The CAM of the FlexStack harnesses (make_cam in ../rust/src/main.rs) ────
static asn1::r2::Cam make_cam(std::uint32_t station_id, const Runtime* runtime)
{
    asn1::r2::Cam msg;
    msg->header.protocolVersion = 2;
    msg->header.messageId = Vanetza_ITS2_MessageId_cam;
    msg->header.stationId = station_id;
    long gdt = 0;
    if (runtime) {
        gdt = std::chrono::duration_cast<std::chrono::milliseconds>(runtime->now().time_since_epoch()).count() % 65536;
    }
    msg->cam.generationDeltaTime = gdt;
    auto& basic = msg->cam.camParameters.basicContainer;
    basic.stationType = Vanetza_ITS2_TrafficParticipantType_passengerCar;
    basic.referencePosition.latitude = 415520000;
    basic.referencePosition.longitude = 21340000;
    basic.referencePosition.positionConfidenceEllipse.semiMajorAxisLength = 4095;
    basic.referencePosition.positionConfidenceEllipse.semiMinorAxisLength = 4095;
    basic.referencePosition.positionConfidenceEllipse.semiMajorAxisOrientation = 3601;
    basic.referencePosition.altitude.altitudeValue = 12000;
    basic.referencePosition.altitude.altitudeConfidence = 15; // unavailable
    auto& hf = msg->cam.camParameters.highFrequencyContainer;
    hf.present = Vanetza_ITS2_HighFrequencyContainer_PR_basicVehicleContainerHighFrequency;
    auto& b = hf.choice.basicVehicleContainerHighFrequency;
    b.heading.headingValue = 900;
    b.heading.headingConfidence = 127;
    b.speed.speedValue = 0;
    b.speed.speedConfidence = 127;
    b.driveDirection = 2;                     // unavailable
    b.vehicleLength.vehicleLengthValue = 1023;
    b.vehicleLength.vehicleLengthConfidenceIndication = 4; // unavailable
    b.vehicleWidth = 62;
    b.longitudinalAcceleration.value = 161;
    b.longitudinalAcceleration.confidence = 102;
    b.curvature.curvatureValue = 1023;
    b.curvature.curvatureConfidence = 7;      // unavailable
    b.curvatureCalculationMode = 2;           // unavailable
    b.yawRate.yawRateValue = 32767;
    b.yawRate.yawRateConfidence = 8;          // unavailable
    return msg;
}

// ── Security entity and positioning, through socktap's option-driven set-up ──
struct Setup {
    boost::asio::io_context io;
    TimeTrigger trigger { io };
    std::unique_ptr<PositionProvider> positioning;
    std::unique_ptr<security::SecurityEntity> security;
};

static std::unique_ptr<Setup> make_setup(const Args& a, bool secured)
{
    po::options_description desc;
    add_positioning_options(desc);
    add_security_options(desc);
    std::string at = a.certs_dir + "/at" + std::to_string(a.at);
    std::vector<std::string> argv { "--positioning", "static", "--latitude", "41.552", "--longitude", "2.134" };
    if (secured) {
        argv.insert(argv.end(), { "--security", "certs", "--crypto-backend", a.backend,
            "--certificate", at + ".cert", "--certificate-key", at + ".pem",
            "--certificate-chain", a.certs_dir + "/aa.cert", a.certs_dir + "/root_ca.cert" });
    } else {
        argv.insert(argv.end(), { "--security", "none" });
    }
    po::variables_map vm;
    po::store(po::command_line_parser(argv).options(desc).run(), vm);
    po::notify(vm);
    auto s = std::make_unique<Setup>();
    s->positioning = create_position_provider(s->io, vm, s->trigger.runtime());
    if (secured) {
        s->security = create_security_entity(vm, s->trigger.runtime(), *s->positioning);
    }
    return s;
}

// ── Codec ────────────────────────────────────────────────────────────────────
static int bench_codec(const Args& a)
{
    bool encode = a.mode == "codec-encode";
    ByteBuffer encoded = make_cam(12345, nullptr).encode();
    std::printf("  CAM encoded size: %zu bytes\n", encoded.size());
    auto once = [&]() {
        if (encode) {
            volatile auto n = make_cam(12345, nullptr).encode().size();
            (void) n;
        } else {
            asn1::r2::Cam cam;
            volatile bool ok = cam.decode(encoded);
            (void) ok;
        }
    };
    auto warm_end = SteadyClock::now() + std::chrono::seconds(a.warmup);
    while (SteadyClock::now() < warm_end) once();
    std::vector<double> lat;
    lat.reserve(5000000);
    ResourceSnapshot res;
    auto start = SteadyClock::now(), end = start + std::chrono::seconds(a.duration);
    Pacer pacer(a.rate, start);
    while (SteadyClock::now() < end && pacer.wait(end)) {
        auto t0 = SteadyClock::now();
        once();
        lat.push_back(us_since(t0));
    }
    double elapsed = std::chrono::duration<double>(SteadyClock::now() - start).count();
    write_row(a, "off", elapsed, lat.size(), lat, 0.0, res.finish());
    return 0;
}

// ── Security (SN-ENCAP / SN-DECAP through Vanetza's security entity) ─────────
static security::EncapRequest sign_request(const ByteBuffer& payload)
{
    security::SignRequest request;
    request.plain_message.layer(OsiLayer::Application) = ByteBuffer(payload);
    request.its_aid = aid::CA;
    return security::EncapRequest(std::move(request));
}

static int bench_security(const Args& a)
{
    bool sign = a.mode == "security-sign";
    auto setup = make_setup(a, true);
    setup->trigger.schedule();
    auto& entity = *setup->security;
    ByteBuffer payload = make_cam(12345, nullptr).encode();
    std::printf("  CAM payload size: %zu bytes\n", payload.size());

    // One signed message (the first CAM of the policy carries the AT) for verify.
    auto first = entity.encapsulate_packet(sign_request(payload));
    const auto* secured = first.secured_message();
    if (!secured) { std::cerr << "signing failed\n"; return 1; }
    ByteBuffer signed_bytes = boost::get<security::v3::SecuredMessage>(*secured).encode();
    std::printf("  Signed message size: %zu bytes\n", signed_bytes.size());

    auto once = [&]() -> bool {
        setup->trigger.schedule(); // runtime clock for the generation time
        if (sign) {
            auto confirm = entity.encapsulate_packet(sign_request(payload));
            return confirm.secured_message() != nullptr;
        }
        security::v3::SecuredMessage msg;
        if (!msg.decode(signed_bytes)) return false;
        security::SecuredMessage variant(std::move(msg));
        auto confirm = entity.decapsulate_packet(security::DecapRequest(security::SecuredMessageView(variant)));
        return security::is_successful(confirm.report);
    };
    if (!once()) { std::cerr << a.mode << " failed on the first message\n"; return 1; }
    auto warm_end = SteadyClock::now() + std::chrono::seconds(a.warmup);
    while (SteadyClock::now() < warm_end) once();
    std::vector<double> lat;
    lat.reserve(500000);
    std::size_t failed = 0;
    ResourceSnapshot res;
    auto start = SteadyClock::now(), end = start + std::chrono::seconds(a.duration);
    Pacer pacer(a.rate, start);
    while (SteadyClock::now() < end && pacer.wait(end)) {
        auto t0 = SteadyClock::now();
        bool ok = once();
        double us = us_since(t0);
        if (ok) lat.push_back(us); else ++failed;
    }
    double elapsed = std::chrono::duration<double>(SteadyClock::now() - start).count();
    if (failed) std::printf("  WARNING: %zu operations failed (not counted)\n", failed);
    Resources r = res.finish();
    double m = mean(lat);
    write_row(a, "on", elapsed, lat.size(), lat, m, r);
    return 0;
}

// ── TX / RX: Vanetza's router, BTP dispatcher and socktap's raw socket link ──
// CA application: socktap's Application::request path (BTP-B header, SHB
// request with the CAM ITS-AID), sending through the router directly.
class BenchCam : public btp::IndicationInterface
{
public:
    using DataIndication = btp::DataIndication;
    using UpPacketPtr = geonet::Router::UpPacketPtr;
    using DownPacketPtr = geonet::Router::DownPacketPtr;

    BenchCam(Runtime& rt, geonet::Router& router, std::uint32_t station) :
        runtime_(rt), router_(router), station_(station) {}

    bool send()
    {
        DownPacketPtr packet { new DownPacket() };
        packet->layer(OsiLayer::Application) = make_cam(station_, &runtime_);
        btp::HeaderB btp_header;
        btp_header.destination_port = btp::ports::CAM;
        btp_header.destination_port_info = host_cast<uint16_t>(0);
        packet->layer(OsiLayer::Transport) = btp_header;
        geonet::ShbDataRequest request(router_.get_mib());
        request.upper_protocol = geonet::UpperProtocol::BTP_B;
        request.communication_profile = geonet::CommunicationProfile::ITS_G5;
        request.its_aid = aid::CA;
        return router_.request(request, std::move(packet)).accepted();
    }

    void indicate(const DataIndication&, UpPacketPtr packet) override
    {
        asn1::PacketVisitor<asn1::r2::Cam> visitor;
        decoded_ = static_cast<bool>(boost::apply_visitor(visitor, *packet));
    }

    bool decoded_ = false;

private:
    Runtime& runtime_;
    geonet::Router& router_;
    std::uint32_t station_;
};

// Times SN-DECAP of received packets (the verify share of RX, sign_latency_mean).
class TimedSecurity : public security::SecurityEntity
{
public:
    explicit TimedSecurity(security::SecurityEntity& inner) : inner_(inner) {}
    security::EncapConfirm encapsulate_packet(security::EncapRequest&& r) override { return inner_.encapsulate_packet(std::move(r)); }
    security::DecapConfirm decapsulate_packet(security::DecapRequest&& r) override
    {
        auto t0 = SteadyClock::now();
        auto c = inner_.decapsulate_packet(std::move(r));
        if (recording) verify_us.push_back(us_since(t0));
        return c;
    }
    bool recording = false;
    std::vector<double> verify_us;
private:
    security::SecurityEntity& inner_;
};

struct Station {
    std::unique_ptr<Setup> setup;
    EthernetDevice device;
    std::unique_ptr<LinkLayer> link;
    geonet::MIB mib;
    std::unique_ptr<geonet::Router> router;
    btp::PortDispatcher dispatcher;
    std::unique_ptr<DccPassthrough> dcc;
    std::unique_ptr<TimedSecurity> timed;
    std::unique_ptr<BenchCam> app;
    SteadyClock::time_point rx_t0;

    Station(const Args& a, bool secured) : setup(make_setup(a, secured)), device(a.interface.c_str())
    {
        po::variables_map vm;
        link = create_link_layer(setup->io, device, "ethernet", vm);
        mib.itsGnLocalGnAddr.mid(device.address());
        mib.itsGnLocalGnAddr.is_manually_configured(true);
        mib.itsGnLocalAddrConfMethod = geonet::AddrConfMethod::Managed;
        mib.itsGnSecurity = secured;
        mib.itsGnBeaconServiceRetransmitTimer = 100000.0 * units::si::seconds; // no Beacons (as FlexStack's harness)
        router.reset(new geonet::Router(setup->trigger.runtime(), mib));
        router->set_address(mib.itsGnLocalGnAddr);
        router->set_transport_handler(geonet::UpperProtocol::BTP_B, &dispatcher);
        if (secured) {
            timed.reset(new TimedSecurity(*setup->security));
            router->set_security_entity(timed.get());
        }
        router->update_position(setup->positioning->position_fix());
        link->set_source_address(mib.itsGnLocalGnAddr.mid());
        dcc.reset(new DccPassthrough(*link, setup->trigger));
        router->set_access_interface(dcc.get());
        link->indicate([this](CohesivePacket&& packet, const EthernetHeader& hdr) {
            if (hdr.source != mib.itsGnLocalGnAddr.mid() && hdr.type == access::ethertype::GeoNetworking) {
                rx_t0 = SteadyClock::now();
                std::unique_ptr<PacketVariant> up { new PacketVariant(std::move(packet)) };
                setup->trigger.schedule();
                router->indicate(std::move(up), hdr.source, hdr.destination);
                on_frame();
            }
        });
        app.reset(new BenchCam(setup->trigger.runtime(), *router, 0xBE000000u | device.address().octets[5]));
        dispatcher.set_non_interactive_handler(btp::ports::CAM, app.get());
        setup->trigger.schedule();
    }

    // RX bookkeeping, set by bench_rx.
    std::function<void()> on_frame = [] {};
};

static int bench_tx(const Args& a)
{
    bool secured = a.security == "on";
    Station st(a, secured);
    auto warm_end = SteadyClock::now() + std::chrono::seconds(a.warmup);
    std::printf("  Warm-up phase (%us)...\n", a.warmup);
    while (SteadyClock::now() < warm_end) st.app->send();
    std::printf("  Measurement phase (%us)...\n", a.duration);
    std::vector<double> lat;
    lat.reserve(5000000);
    std::size_t rejected = 0;
    ResourceSnapshot res;
    auto start = SteadyClock::now(), end = start + std::chrono::seconds(a.duration);
    Pacer pacer(a.rate, start);
    while (SteadyClock::now() < end && pacer.wait(end)) {
        auto t0 = SteadyClock::now();
        bool ok = st.app->send(); // returns once the frame is handed to the socket
        double us = us_since(t0);
        if (ok) lat.push_back(us); else ++rejected;
    }
    double elapsed = std::chrono::duration<double>(SteadyClock::now() - start).count();
    if (rejected) std::printf("  WARNING: %zu requests rejected by the router (not counted)\n", rejected);
    write_row(a, a.security, elapsed, lat.size(), lat, 0.0, res.finish());
    return 0;
}

static int bench_rx(const Args& a)
{
    bool secured = a.security == "on";
    Station st(a, secured);
    std::vector<double> lat;
    lat.reserve(5000000);
    bool measuring = false;
    std::size_t undecodable = 0;
    st.on_frame = [&] {
        if (!measuring) return;
        if (st.app->decoded_) {
            lat.push_back(us_since(st.rx_t0));
        } else {
            ++undecodable; // dropped by GN / security, or not a CAM
        }
        st.app->decoded_ = false;
    };
    std::printf("  Warm-up phase (%us) - waiting for packets from remote sender...\n", a.warmup);
    st.setup->io.run_for(std::chrono::seconds(a.warmup));
    st.setup->io.restart();
    std::printf("  Measurement phase (%us)...\n", a.duration);
    if (st.timed) st.timed->recording = true;
    measuring = true;
    ResourceSnapshot res;
    auto start = SteadyClock::now();
    st.setup->io.run_for(std::chrono::seconds(a.duration));
    double elapsed = std::chrono::duration<double>(SteadyClock::now() - start).count();
    measuring = false;
    double verify_mean = st.timed ? mean(st.timed->verify_us) : 0.0;
    std::printf("  RX: %zu CAMs, %zu frames not delivered as CAM\n", lat.size(), undecodable);
    write_row(a, a.security, elapsed, lat.size(), lat, verify_mean, res.finish());
    return 0;
}

int main(int argc, const char** argv)
{
    Args a;
    po::options_description opts("flexstack-bench-vanetza");
    opts.add_options()
        ("help", "Show options")
        ("mode", po::value(&a.mode)->required(), "tx | rx | codec-encode | codec-decode | security-sign | security-verify")
        ("security", po::value(&a.security)->default_value("off"), "off | on")
        ("duration", po::value(&a.duration)->default_value(60), "Measurement duration (s)")
        ("warmup", po::value(&a.warmup)->default_value(5), "Warm-up duration (s)")
        ("rate", po::value(&a.rate)->default_value(0), "Fixed rate in msg/s (0 = max)")
        ("output", po::value(&a.output)->default_value("../results/results.csv"), "CSV output")
        ("run-id", po::value(&a.run_id)->default_value("1"), "Run id")
        ("platform", po::value(&a.platform)->default_value("laptop"), "Platform label")
        ("interface", po::value(&a.interface)->default_value("lo"), "Network interface (tx, rx)")
        ("certs-dir", po::value(&a.certs_dir)->default_value("certs"), "Benchmark certificate chain")
        ("at", po::value(&a.at)->default_value(1), "Own AT (1 or 2)")
        ("crypto-backend", po::value(&a.backend)->default_value("OpenSSL"), "Vanetza crypto backend");
    po::variables_map vm;
    try {
        po::store(po::parse_command_line(argc, argv, opts), vm);
        if (vm.count("help")) { std::cout << opts << "\n"; return 0; }
        po::notify(vm);
    } catch (const std::exception& e) {
        std::cerr << e.what() << "\n" << opts << "\n";
        return 2;
    }
    std::printf("============================================================\n"
                "FlexStack Benchmark - Vanetza (%s backend)\n"
                "============================================================\n"
                "  Mode     : %s\n  Security : %s\n  Duration : %us\n  Warm-up  : %us\n"
                "  Platform : %s\n  Interface: %s\n  Run ID   : %s\n  Output   : %s\n",
                a.backend.c_str(), a.mode.c_str(), a.security.c_str(), a.duration, a.warmup,
                a.platform.c_str(), a.interface.c_str(), a.run_id.c_str(), a.output.c_str());
    try {
        if (a.mode == "codec-encode" || a.mode == "codec-decode") return bench_codec(a);
        if (a.mode == "security-sign" || a.mode == "security-verify") return bench_security(a);
        if (a.mode == "tx") return bench_tx(a);
        if (a.mode == "rx") return bench_rx(a);
        std::cerr << "unknown mode " << a.mode << "\n";
        return 2;
    } catch (const std::exception& e) {
        std::cerr << "Exit: " << e.what() << "\n";
        return 1;
    }
}
