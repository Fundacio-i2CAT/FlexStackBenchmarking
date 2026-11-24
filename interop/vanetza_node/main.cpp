// Vanetza interoperability node for the FlexStack signed-interop matrix.
//
// Same set-up as Vanetza's socktap (ethernet link layer, static position,
// security entity built by socktap's create_security_entity from --security
// certs --certificate --certificate-key --certificate-chain), with:
//   * the security entity wrapped by LoggingSecurityEntity (verdict log);
//   * release-2 CAM / DENM applications (interop_applications.hpp);
//   * JSON-lines log on stdout (../README.md, "Log format").

#include "ethernet_device.hpp"
#include "interop_applications.hpp"
#include "interop_log.hpp"
#include "link_layer.hpp"
#include "logging_security_entity.hpp"
#include "positioning.hpp"
#include "router_context.hpp"
#include "security.hpp"
#include "time_trigger.hpp"
#include <boost/asio/io_context.hpp>
#include <boost/asio/signal_set.hpp>
#include <boost/program_options.hpp>
#include <chrono>
#include <iostream>
#include <memory>

namespace asio = boost::asio;
namespace gn = vanetza::geonet;
namespace po = boost::program_options;
using namespace vanetza;

int main(int argc, const char** argv)
{
    po::options_description options("Allowed options");
    options.add_options()
        ("help", "Print out available options.")
        ("link-layer,l", po::value<std::string>()->default_value("ethernet"), "Link layer type")
        ("interface,i", po::value<std::string>()->default_value("eth0"), "Network interface to use.")
        ("node", po::value<std::string>()->default_value("vanetza"), "Node name in the log.")
        ("station-id", po::value<unsigned>()->default_value(3), "Station ID of generated messages.")
        ("cam-interval", po::value<unsigned>()->default_value(100), "CAM interval in ms (0: no CAMs).")
        ("denm-interval", po::value<unsigned>()->default_value(1000), "DENM interval in ms (0: no DENMs).")
    ;
    add_positioning_options(options);
    add_security_options(options);
    add_link_layer_options(options);

    po::variables_map vm;
    try {
        po::store(po::parse_command_line(argc, argv, options), vm);
        po::notify(vm);
    } catch (po::error& e) {
        std::cerr << "ERROR: " << e.what() << "\n\n" << options << std::endl;
        return 1;
    }
    if (vm.count("help")) {
        std::cout << options << std::endl;
        return 1;
    }

    try {
        const std::string node = vm["node"].as<std::string>();
        asio::io_context io_context;
        TimeTrigger trigger(io_context);

        const std::string device_name = vm["interface"].as<std::string>();
        EthernetDevice device(device_name.c_str());
        const vanetza::MacAddress mac_address = device.address();

        auto link_layer = create_link_layer(io_context, device, vm["link-layer"].as<std::string>(), vm);
        if (!link_layer) {
            std::cerr << "link layer not available" << std::endl;
            return 1;
        }

        asio::signal_set signals(io_context, SIGINT, SIGTERM);
        signals.async_wait([&io_context](const boost::system::error_code& ec, int) {
            if (!ec) {
                io_context.stop();
            }
        });

        gn::MIB mib;
        mib.itsGnLocalGnAddr.mid(mac_address);
        mib.itsGnLocalGnAddr.is_manually_configured(true);
        mib.itsGnLocalAddrConfMethod = geonet::AddrConfMethod::Managed;
        mib.itsGnSecurity = false;
        mib.itsGnProtocolVersion = 1;

        auto positioning = create_position_provider(io_context, vm, trigger.runtime());
        if (!positioning) {
            std::cerr << "positioning not available" << std::endl;
            return 1;
        }

        std::unique_ptr<security::SecurityEntity> security;
        if (auto inner = create_security_entity(vm, trigger.runtime(), *positioning)) {
            security.reset(new interop::LoggingSecurityEntity(std::move(inner), node));
            mib.itsGnSecurity = true;
        }

        RouterContext context(mib, trigger, *positioning, security.get());
        context.set_link_layer(link_layer.get());

        const unsigned station_id = vm["station-id"].as<unsigned>();
        InteropCamApplication cam(*positioning, trigger.runtime(), node, station_id,
            std::chrono::milliseconds(vm["cam-interval"].as<unsigned>()));
        InteropDenmApplication denm(*positioning, trigger.runtime(), node, station_id,
            std::chrono::milliseconds(vm["denm-interval"].as<unsigned>()));
        context.enable(&cam);
        context.enable(&denm);

        interop::Event(node, "start")
            .str("stack", "vanetza")
            .str("security", vm["security"].as<std::string>())
            .str("backend", vm["crypto-backend"].as<std::string>());
        io_context.run();
        interop::Event(node, "stop");
    } catch (std::exception& e) {
        std::cerr << "Exit: " << e.what() << std::endl;
        return 1;
    }
    return 0;
}
