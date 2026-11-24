# Vanetza benchmark harness (WP-D). Built inside the Vanetza source tree
# (tools/bench_node, added by build.sh) next to socktap, whose link-layer,
# positioning and security set-up it reuses unchanged.
set(SOCKTAP_DIR ${PROJECT_SOURCE_DIR}/tools/socktap)
add_executable(flexstack-bench-vanetza
    bench_main.cpp
    ${SOCKTAP_DIR}/dcc_passthrough.cpp
    ${SOCKTAP_DIR}/ethernet_device.cpp
    ${SOCKTAP_DIR}/link_layer.cpp
    ${SOCKTAP_DIR}/positioning.cpp
    ${SOCKTAP_DIR}/raw_socket_link.cpp
    ${SOCKTAP_DIR}/security.cpp
    ${SOCKTAP_DIR}/tcp_link.cpp
    ${SOCKTAP_DIR}/time_trigger.cpp
    ${SOCKTAP_DIR}/udp_link.cpp
    ${SOCKTAP_DIR}/certificate_validation_v3.cpp
    ${SOCKTAP_DIR}/certificate_validation_v3_strict.cpp
)
target_include_directories(flexstack-bench-vanetza PRIVATE ${SOCKTAP_DIR})
target_link_libraries(flexstack-bench-vanetza PUBLIC Boost::program_options Threads::Threads vanetza)
install(TARGETS flexstack-bench-vanetza DESTINATION ${CMAKE_INSTALL_BINDIR})
