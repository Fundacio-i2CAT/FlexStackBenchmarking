// Vanetza interoperability node: security entity decorator.
//
// Wraps the security entity that socktap builds (unchanged Vanetza sign and
// verify services) and logs the outcome of every SN-ENCAP / SN-DECAP: the
// verification report Vanetza computed, the ITS-AID, the signer identifier
// type (digest or certificate) and the HashedId8 of the signer's AT. Nothing
// is changed in the packets or in the verdicts.

#pragma once

#include "interop_log.hpp"
#include <vanetza/security/decap_service.hpp>
#include <vanetza/security/encap_service.hpp>
#include <vanetza/security/security_entity.hpp>
#include <vanetza/security/sign_service.hpp>
#include <vanetza/security/v2/secured_message.hpp>
#include <vanetza/security/v3/secured_message.hpp>
#include <boost/variant/apply_visitor.hpp>
#include <boost/variant/get.hpp>
#include <boost/variant/static_visitor.hpp>
#include <memory>
#include <string>

namespace interop
{

struct SignerInfo
{
    std::string type = "none"; // digest | certificate | none | v2
    std::string at;            // HashedId8 of the signer's AT, hex ("" if unknown)
};

struct SignerVisitor : public boost::static_visitor<SignerInfo>
{
    SignerInfo operator()(const vanetza::security::v2::SecuredMessage&) const
    {
        SignerInfo info;
        info.type = "v2";
        return info;
    }

    SignerInfo operator()(const vanetza::security::v3::SecuredMessage& msg) const
    {
        namespace v3 = vanetza::security::v3;
        SignerInfo info;
        const auto signer = msg.signer_identifier();
        if (const auto* digest = boost::get<const v3::asn1::HashedId8*>(&signer)) {
            if (*digest) {
                info.type = "digest";
            }
        } else if (const auto* cert = boost::get<const v3::asn1::Certificate*>(&signer)) {
            if (*cert) {
                info.type = "certificate";
            }
        }
        if (info.type != "none") {
            const auto id = v3::get_certificate_id(signer);
            if (id) {
                info.at = hex(*id);
            }
        }
        return info;
    }
};

inline std::string report_name(vanetza::security::VerificationReport report)
{
    using R = vanetza::security::VerificationReport;
    switch (report) {
        case R::Success: return "Success";
        case R::False_Signature: return "False_Signature";
        case R::Invalid_Certificate: return "Invalid_Certificate";
        case R::Revoked_Certificate: return "Revoked_Certificate";
        case R::Inconsistent_Chain: return "Inconsistent_Chain";
        case R::Invalid_Timestamp: return "Invalid_Timestamp";
        case R::Duplicate_Message: return "Duplicate_Message";
        case R::Invalid_Mobility_Data: return "Invalid_Mobility_Data";
        case R::Unsigned_Message: return "Unsigned_Message";
        case R::Signer_Certificate_Not_Found: return "Signer_Certificate_Not_Found";
        case R::Unsupported_Signer_Identifier_Type: return "Unsupported_Signer_Identifier_Type";
        case R::Incompatible_Protocol: return "Incompatible_Protocol";
        case R::Configuration_Problem: return "Configuration_Problem";
    }
    return "Unknown";
}

struct DecapReportVisitor : public boost::static_visitor<std::string>
{
    std::string operator()(const boost::blank&) const { return "Unsecured"; }
    std::string operator()(vanetza::security::VerificationReport r) const { return report_name(r); }
};

class LoggingSecurityEntity : public vanetza::security::SecurityEntity
{
public:
    LoggingSecurityEntity(std::unique_ptr<vanetza::security::SecurityEntity> inner, std::string node) :
        m_inner(std::move(inner)), m_node(std::move(node))
    {
    }

    vanetza::security::EncapConfirm encapsulate_packet(vanetza::security::EncapRequest&& request) override
    {
        long long its_aid = -1;
        if (const auto* sign = boost::get<vanetza::security::SignRequest>(&request)) {
            its_aid = sign->its_aid;
        }
        auto confirm = m_inner->encapsulate_packet(std::move(request));
        Event event(m_node, "tx");
        event.num("its_aid", its_aid);
        if (const auto* msg = confirm.secured_message()) {
            SignerVisitor visitor;
            const SignerInfo info = boost::apply_visitor(visitor, *msg);
            event.str("signer", info.type).str("at", info.at).boolean("signed", true);
        } else {
            event.boolean("signed", false);
        }
        return confirm;
    }

    vanetza::security::DecapConfirm decapsulate_packet(vanetza::security::DecapRequest&& request) override
    {
        SignerVisitor signer_visitor;
        const SignerInfo info = request.sec_packet.apply_visitor(signer_visitor);
        const long long its_aid = vanetza::security::get_its_aid(request.sec_packet);
        auto confirm = m_inner->decapsulate_packet(std::move(request));
        DecapReportVisitor report_visitor;
        Event(m_node, "rx")
            .num("its_aid", its_aid)
            .str("signer", info.type)
            .str("at", info.at)
            .str("report", boost::apply_visitor(report_visitor, confirm.report))
            .boolean("verified", vanetza::security::is_successful(confirm.report));
        return confirm;
    }

private:
    std::unique_ptr<vanetza::security::SecurityEntity> m_inner;
    std::string m_node;
};

} // namespace interop
