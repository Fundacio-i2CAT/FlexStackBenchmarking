// Vanetza interoperability node: JSON-lines event log.
//
// Every event is one JSON object on stdout, the same schema as the FlexStack
// Python and Rust interop nodes (see ../README.md, "Log format").

#pragma once

#include <chrono>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>

namespace interop
{

inline std::string hex(const std::uint8_t* data, std::size_t length)
{
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (std::size_t i = 0; i < length; ++i) {
        out << std::setw(2) << static_cast<unsigned>(data[i]);
    }
    return out.str();
}

template<typename Container>
std::string hex(const Container& bytes)
{
    return hex(bytes.data(), bytes.size());
}

/// One JSON line: {"t_ms": ..., "node": ..., "event": ..., <fields>}
class Event
{
public:
    Event(const std::string& node, const std::string& event)
    {
        const auto now = std::chrono::system_clock::now().time_since_epoch();
        m_out << "{\"t_ms\":" << std::chrono::duration_cast<std::chrono::milliseconds>(now).count()
              << ",\"node\":\"" << node << "\",\"event\":\"" << event << "\"";
    }

    Event& str(const char* key, const std::string& value)
    {
        m_out << ",\"" << key << "\":\"" << value << "\"";
        return *this;
    }

    Event& num(const char* key, long long value)
    {
        m_out << ",\"" << key << "\":" << value;
        return *this;
    }

    Event& boolean(const char* key, bool value)
    {
        m_out << ",\"" << key << "\":" << (value ? "true" : "false");
        return *this;
    }

    ~Event()
    {
        static std::mutex mutex;
        std::lock_guard<std::mutex> lock(mutex);
        std::cout << m_out.str() << "}" << std::endl;
    }

private:
    std::ostringstream m_out;
};

} // namespace interop
