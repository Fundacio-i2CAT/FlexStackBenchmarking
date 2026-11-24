// Vanetza interoperability node: CAM and DENM applications.
//
// Release 2 messages (ETSI TS 103 900 V2.3.1 CAM, TS 103 831 V2.3.1 DENM, the
// versions FlexStack implements) built with Vanetza's own ASN.1 bindings and
// sent through the unchanged Vanetza BTP / GeoNetworking / security stack.
// Received messages are decoded and logged (facility-level result); the
// security verdict is logged by LoggingSecurityEntity.

#pragma once

#include "application.hpp"
#include <vanetza/common/clock.hpp>
#include <vanetza/common/position_provider.hpp>
#include <vanetza/common/runtime.hpp>
#include <cstdint>
#include <string>

class InteropCamApplication : public Application
{
public:
    InteropCamApplication(vanetza::PositionProvider&, vanetza::Runtime&, std::string node,
                          std::uint32_t station_id, vanetza::Clock::duration interval);
    PortType port() override;
    void indicate(const DataIndication&, UpPacketPtr) override;

private:
    void schedule();
    void on_timer(vanetza::Clock::time_point);

    vanetza::PositionProvider& positioning_;
    vanetza::Runtime& runtime_;
    std::string node_;
    std::uint32_t station_id_;
    vanetza::Clock::duration interval_;
};

class InteropDenmApplication : public Application
{
public:
    InteropDenmApplication(vanetza::PositionProvider&, vanetza::Runtime&, std::string node,
                           std::uint32_t station_id, vanetza::Clock::duration interval);
    PortType port() override;
    void indicate(const DataIndication&, UpPacketPtr) override;

private:
    void schedule();
    void on_timer(vanetza::Clock::time_point);

    vanetza::PositionProvider& positioning_;
    vanetza::Runtime& runtime_;
    std::string node_;
    std::uint32_t station_id_;
    vanetza::Clock::duration interval_;
    long sequence_number_ = 0;
};
