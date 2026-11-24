# Vanetza interoperability node. Built inside the Vanetza source tree
# (tools/interop_node, added by interop/docker/Dockerfile) next to socktap, whose
# link-layer, positioning, router and security set-up it reuses unchanged.

set(SOCKTAP_DIR ${PROJECT_SOURCE_DIR}/tools/socktap)

add_executable(vanetza-interop-node
    main.cpp
    interop_applications.cpp
    ${SOCKTAP_DIR}/application.cpp
    ${SOCKTAP_DIR}/dcc_passthrough.cpp
    ${SOCKTAP_DIR}/ethernet_device.cpp
    ${SOCKTAP_DIR}/link_layer.cpp
    ${SOCKTAP_DIR}/positioning.cpp
    ${SOCKTAP_DIR}/raw_socket_link.cpp
    ${SOCKTAP_DIR}/router_context.cpp
    ${SOCKTAP_DIR}/security.cpp
    ${SOCKTAP_DIR}/tcp_link.cpp
    ${SOCKTAP_DIR}/time_trigger.cpp
    ${SOCKTAP_DIR}/udp_link.cpp
    ${SOCKTAP_DIR}/certificate_validation_v3.cpp
    ${SOCKTAP_DIR}/certificate_validation_v3_strict.cpp
)
target_include_directories(vanetza-interop-node PRIVATE ${SOCKTAP_DIR})
target_link_libraries(vanetza-interop-node PUBLIC Boost::program_options Threads::Threads vanetza)
install(TARGETS vanetza-interop-node DESTINATION ${CMAKE_INSTALL_BINDIR})
