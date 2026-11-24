### rogue-openssl

| Sender | Receiver | Message | Signer | Sent | Received | Verified | AT not yet known | Refused (report) |
|---|---|---|---|---:|---:|---:|---:|---|
| python | rogue | CAM | certificate | 2796 | 2796 | 0 | 0 | 2796 (INCONSISTENT_CHAIN 2796) |
| python | rogue | CAM | digest | 24 | 24 | 0 | 24 | 0 (-) |
| python | rogue | DENM | certificate | 296 | 1332 | 0 | 0 | 1332 (INCONSISTENT_CHAIN 1332) |
| python | rust | CAM | certificate | 2798 | 2798 | 2798 | 0 | 0 (-) |
| python | rust | CAM | digest | 31 | 31 | 31 | 0 | 0 (-) |
| python | rust | DENM | certificate | 296 | 1036 | 1036 | 0 | 0 (-) |
| python | vanetza | CAM | certificate | 2798 | 2798 | 1 | 0 | 2797 (False_Signature 2797) |
| python | vanetza | CAM | digest | 31 | 31 | 7 | 1 | 23 (False_Signature 23) |
| python | vanetza | DENM | certificate | 296 | 888 | 888 | 0 | 0 (-) |
| rogue | python | CAM | certificate | 2870 | 2872 | 0 | 0 | 2872 (INCONSISTENT_CHAIN 2872) |
| rogue | python | DENM | certificate | 296 | 974 | 0 | 0 | 974 (INCONSISTENT_CHAIN 974) |
| rogue | rust | CAM | certificate | 2881 | 2883 | 0 | 0 | 2883 (InconsistentChain 2883) |
| rogue | rust | DENM | certificate | 297 | 978 | 0 | 0 | 978 (InconsistentChain 978) |
| rogue | vanetza | CAM | certificate | 2882 | 2884 | 0 | 0 | 2884 (False_Signature 2884) |
| rogue | vanetza | DENM | certificate | 297 | 594 | 594 | 0 | 0 (-) |
| rust | python | CAM | certificate | 2894 | 2896 | 2896 | 0 | 0 (-) |
| rust | python | CAM | digest | 83 | 83 | 82 | 1 | 0 (-) |
| rust | python | DENM | certificate | 596 | 1040 | 1040 | 0 | 0 (-) |
| rust | rogue | CAM | certificate | 2906 | 2906 | 0 | 0 | 2906 (INCONSISTENT_CHAIN 2906) |
| rust | rogue | CAM | digest | 75 | 75 | 0 | 75 | 0 (-) |
| rust | rogue | DENM | certificate | 596 | 1338 | 0 | 0 | 1338 (INCONSISTENT_CHAIN 1338) |
| rust | vanetza | CAM | certificate | 2910 | 2910 | 4 | 0 | 2906 (False_Signature 2906) |
| rust | vanetza | CAM | digest | 102 | 102 | 27 | 1 | 74 (False_Signature 74) |
| rust | vanetza | DENM | certificate | 602 | 900 | 900 | 0 | 0 (-) |
| vanetza | python | CAM | certificate | 2871 | 2873 | 2873 | 0 | 0 (-) |
| vanetza | python | CAM | digest | 108 | 108 | 108 | 0 | 0 (-) |
| vanetza | python | DENM | certificate | 298 | 846 | 846 | 0 | 0 (-) |
| vanetza | rogue | CAM | certificate | 2883 | 2884 | 0 | 0 | 2884 (INCONSISTENT_CHAIN 2884) |
| vanetza | rogue | CAM | digest | 102 | 102 | 0 | 102 | 0 (-) |
| vanetza | rogue | DENM | certificate | 298 | 1144 | 0 | 0 | 1144 (INCONSISTENT_CHAIN 1144) |
| vanetza | rust | CAM | certificate | 2886 | 2888 | 2888 | 0 | 0 (-) |
| vanetza | rust | CAM | digest | 127 | 127 | 127 | 0 | 0 (-) |
| vanetza | rust | DENM | certificate | 301 | 852 | 852 | 0 | 0 (-) |

| Sender | Receiver | Facility message | Sent (signed) | Verified | Delivered | CAMs verified, not delivered |
|---|---|---|---:|---:|---:|---:|
| python | rust | CAM | 2829 | 2829 | 2829 | 0 |
| python | rust | DENM | 296 | 1036 | 296 | - |
| python | vanetza | CAM | 2829 | 8 | 8 | 0 |
| python | vanetza | DENM | 296 | 888 | 888 | - |
| rogue | vanetza | DENM | 297 | 594 | 594 | - |
| rust | python | CAM | 2977 | 2978 | 2978 | 0 |
| rust | python | DENM | 596 | 1040 | 298 | - |
| rust | vanetza | CAM | 3012 | 31 | 31 | 0 |
| rust | vanetza | DENM | 602 | 900 | 900 | - |
| vanetza | python | CAM | 2979 | 2981 | 2981 | 0 |
| vanetza | python | DENM | 298 | 846 | 298 | - |
| vanetza | rust | CAM | 3013 | 3015 | 3015 | 0 |
| vanetza | rust | DENM | 301 | 852 | 301 | - |
