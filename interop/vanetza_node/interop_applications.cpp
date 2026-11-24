#include "interop_applications.hpp"
#include "interop_log.hpp"
#include <vanetza/asn1/asn1c_wrapper.hpp>
#include <vanetza/asn1/cam.hpp>
#include <vanetza/asn1/denm.hpp>
#include <vanetza/asn1/packet_visitor.hpp>
#include <vanetza/btp/ports.hpp>
#include <vanetza/common/its_aid.hpp>
#include <vanetza/facilities/cam_functions.hpp>
#include <vanetza/geonet/areas.hpp>
#include <vanetza/common/position_fix.hpp>
#include <vanetza/units/angle.hpp>
#include <vanetza/units/length.hpp>
#include <chrono>
#include <cmath>
#include <functional>
#include <stdexcept>

using namespace vanetza;
using namespace std::chrono;

namespace
{

// TimestampIts: milliseconds since 2004-01-01T00:00:00 (Vanetza's Clock epoch).
std::uint64_t its_timestamp(const Runtime& runtime)
{
    return duration_cast<milliseconds>(runtime.now().time_since_epoch()).count();
}

void fill_reference_position(const PositionFix& fix, Vanetza_ITS2_ReferencePositionWithConfidence_t& pos)
{
    pos.latitude = std::lround(fix.latitude.value() * 1e7);
    pos.longitude = std::lround(fix.longitude.value() * 1e7);
    pos.positionConfidenceEllipse.semiMajorAxisLength = Vanetza_ITS2_SemiAxisLength_unavailable;
    pos.positionConfidenceEllipse.semiMinorAxisLength = Vanetza_ITS2_SemiAxisLength_unavailable;
    pos.positionConfidenceEllipse.semiMajorAxisOrientation = Vanetza_ITS2_Wgs84AngleValue_unavailable;
    pos.altitude.altitudeValue = Vanetza_ITS2_AltitudeValue_unavailable;
    pos.altitude.altitudeConfidence = Vanetza_ITS2_AltitudeConfidence_unavailable;
}

} // namespace

// ── CAM ─────────────────────────────────────────────────────────────────────

InteropCamApplication::InteropCamApplication(PositionProvider& positioning, Runtime& runtime,
        std::string node, std::uint32_t station_id, Clock::duration interval) :
    positioning_(positioning), runtime_(runtime), node_(std::move(node)),
    station_id_(station_id), interval_(interval)
{
    if (interval_ > Clock::duration::zero()) {
        schedule();
    }
}

InteropCamApplication::PortType InteropCamApplication::port()
{
    return btp::ports::CAM;
}

void InteropCamApplication::indicate(const DataIndication& indication, UpPacketPtr packet)
{
    asn1::PacketVisitor<asn1::r2::Cam> visitor;
    std::shared_ptr<const asn1::r2::Cam> cam = boost::apply_visitor(visitor, *packet);
    interop::Event event(node_, "cam");
    event.num("its_aid", indication.its_aid ? static_cast<long long>(*indication.its_aid) : -1);
    event.boolean("decoded", static_cast<bool>(cam));
    if (cam) {
        event.num("station_id", (*cam)->header.stationId);
        event.num("protocol_version", (*cam)->header.protocolVersion);
    }
}

void InteropCamApplication::schedule()
{
    runtime_.schedule(interval_, std::bind(&InteropCamApplication::on_timer, this, std::placeholders::_1), this);
}

void InteropCamApplication::on_timer(Clock::time_point)
{
    schedule();
    auto fix = positioning_.position_fix();
    if (!has_horizontal_position(fix)) {
        return;
    }

    asn1::r2::Cam message;
    message->header.protocolVersion = 2;
    message->header.messageId = Vanetza_ITS2_MessageId_cam;
    message->header.stationId = station_id_;
    message->cam.generationDeltaTime = its_timestamp(runtime_) % 65536;

    auto& basic = message->cam.camParameters.basicContainer;
    basic.stationType = Vanetza_ITS2_TrafficParticipantType_passengerCar;
    fill_reference_position(fix, basic.referencePosition);

    auto& hf = message->cam.camParameters.highFrequencyContainer;
    hf.present = Vanetza_ITS2_HighFrequencyContainer_PR_basicVehicleContainerHighFrequency;
    auto& bvc = hf.choice.basicVehicleContainerHighFrequency;
    bvc.heading.headingValue = 0;
    bvc.heading.headingConfidence = 1;
    bvc.speed.speedValue = 0;
    bvc.speed.speedConfidence = 1;
    bvc.driveDirection = 0; // forward
    bvc.vehicleLength.vehicleLengthValue = 1023; // unavailable
    bvc.vehicleLength.vehicleLengthConfidenceIndication = Vanetza_ITS2_VehicleLengthConfidenceIndication_unavailable;
    bvc.vehicleWidth = Vanetza_ITS2_VehicleWidth_unavailable;
    bvc.longitudinalAcceleration.value = Vanetza_ITS2_AccelerationValue_unavailable;
    bvc.longitudinalAcceleration.confidence = Vanetza_ITS2_AccelerationConfidence_unavailable;
    bvc.curvature.curvatureValue = 1023; // unavailable
    bvc.curvature.curvatureConfidence = Vanetza_ITS2_CurvatureConfidence_unavailable;
    bvc.curvatureCalculationMode = 2; // unavailable
    bvc.yawRate.yawRateValue = 32767; // unavailable
    bvc.yawRate.yawRateConfidence = Vanetza_ITS2_YawRateConfidence_unavailable;

    std::string error;
    if (!message.validate(error)) {
        throw std::runtime_error("invalid CAM: " + error);
    }

    DownPacketPtr packet { new DownPacket() };
    packet->layer(OsiLayer::Application) = std::move(message);

    DataRequest request;
    request.its_aid = aid::CA;
    request.transport_type = geonet::TransportType::SHB;
    request.communication_profile = geonet::CommunicationProfile::ITS_G5;
    auto confirm = Application::request(request, std::move(packet));
    interop::Event(node_, "cam_tx").boolean("accepted", confirm.accepted());
}

// ── DENM ────────────────────────────────────────────────────────────────────

InteropDenmApplication::InteropDenmApplication(PositionProvider& positioning, Runtime& runtime,
        std::string node, std::uint32_t station_id, Clock::duration interval) :
    positioning_(positioning), runtime_(runtime), node_(std::move(node)),
    station_id_(station_id), interval_(interval)
{
    if (interval_ > Clock::duration::zero()) {
        schedule();
    }
}

InteropDenmApplication::PortType InteropDenmApplication::port()
{
    return btp::ports::DENM;
}

void InteropDenmApplication::indicate(const DataIndication& indication, UpPacketPtr packet)
{
    asn1::PacketVisitor<asn1::r2::Denm> visitor;
    std::shared_ptr<const asn1::r2::Denm> denm = boost::apply_visitor(visitor, *packet);
    interop::Event event(node_, "denm");
    event.num("its_aid", indication.its_aid ? static_cast<long long>(*indication.its_aid) : -1);
    event.boolean("decoded", static_cast<bool>(denm));
    if (denm) {
        event.num("station_id", (*denm)->header.stationId);
        event.num("protocol_version", (*denm)->header.protocolVersion);
        event.num("sequence_number", (*denm)->denm.management.actionId.sequenceNumber);
    }
}

void InteropDenmApplication::schedule()
{
    runtime_.schedule(interval_, std::bind(&InteropDenmApplication::on_timer, this, std::placeholders::_1), this);
}

void InteropDenmApplication::on_timer(Clock::time_point)
{
    schedule();
    auto fix = positioning_.position_fix();
    if (!has_horizontal_position(fix)) {
        return;
    }

    // A new event each time (new actionId), as a DENM trigger would create.
    asn1::r2::Denm message;
    message->header.protocolVersion = 2;
    message->header.messageId = Vanetza_ITS2_MessageId_denm;
    message->header.stationId = station_id_;

    auto& management = message->denm.management;
    management.actionId.originatingStationId = station_id_;
    management.actionId.sequenceNumber = sequence_number_;
    sequence_number_ = (sequence_number_ + 1) % 65536;
    const std::uint64_t now = its_timestamp(runtime_);
    asn_uint642INTEGER(&management.detectionTime, now);
    asn_uint642INTEGER(&management.referenceTime, now);
    facilities::copy(fix, management.eventPosition);
    management.stationType = Vanetza_ITS2_TrafficParticipantType_passengerCar;

    auto* situation = asn1::allocate<Vanetza_ITS2_SituationContainer_t>();
    situation->informationQuality = 1;
    situation->eventType.ccAndScc.present = Vanetza_ITS2_CauseCodeChoice_PR_roadworks3;
    situation->eventType.ccAndScc.choice.roadworks3 = 0;
    message->denm.situation = situation;

    std::string error;
    if (!message.validate(error)) {
        throw std::runtime_error("invalid DENM: " + error);
    }

    DownPacketPtr packet { new DownPacket() };
    packet->layer(OsiLayer::Application) = std::move(message);

    geonet::Area area;
    geonet::Circle circle;
    circle.r = 1000.0 * units::si::meters;
    area.shape = circle;
    area.position.latitude = fix.latitude;
    area.position.longitude = fix.longitude;
    area.angle = units::Angle(0.0 * units::degree);

    DataRequest request;
    request.its_aid = aid::DEN;
    request.transport_type = geonet::TransportType::GBC;
    request.destination = area;
    request.communication_profile = geonet::CommunicationProfile::ITS_G5;
    request.maximum_lifetime = geonet::Lifetime(geonet::Lifetime::Base::One_Second, 10);
    auto confirm = Application::request(request, std::move(packet));
    interop::Event(node_, "denm_tx").boolean("accepted", confirm.accepted());
}
