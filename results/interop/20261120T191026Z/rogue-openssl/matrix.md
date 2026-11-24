### rogue-openssl

| Sender | Receiver | Message | Signer | Sent | Received | Verified | AT not yet known | Refused (report) |
|---|---|---|---|---:|---:|---:|---:|---|
| python | rogue | CAM | certificate | 1104 | 1104 | 0 | 0 | 1104 (INCONSISTENT_CHAIN 1104) |
| python | rogue | CAM | digest | 7 | 7 | 0 | 7 | 0 (-) |
| python | rogue | DENM | certificate | 117 | 524 | 0 | 0 | 524 (INCONSISTENT_CHAIN 524) |
| python | rust | CAM | certificate | 1106 | 1106 | 1106 | 0 | 0 (-) |
| python | rust | CAM | digest | 13 | 13 | 13 | 0 | 0 (-) |
| python | rust | DENM | certificate | 117 | 407 | 407 | 0 | 0 (-) |
| python | vanetza | CAM | certificate | 1106 | 1106 | 1 | 0 | 1105 (False_Signature 1105) |
| python | vanetza | CAM | digest | 13 | 13 | 5 | 1 | 7 (False_Signature 7) |
| python | vanetza | DENM | certificate | 117 | 351 | 351 | 0 | 0 (-) |
| rogue | python | CAM | certificate | 1133 | 1135 | 0 | 0 | 1135 (INCONSISTENT_CHAIN 1135) |
| rogue | python | DENM | certificate | 116 | 374 | 0 | 0 | 374 (INCONSISTENT_CHAIN 374) |
| rogue | rust | CAM | certificate | 1144 | 1146 | 0 | 0 | 1146 (InconsistentChain 1146) |
| rogue | rust | DENM | certificate | 118 | 376 | 0 | 0 | 376 (InconsistentChain 376) |
| rogue | vanetza | CAM | certificate | 1145 | 1147 | 0 | 0 | 1147 (False_Signature 1147) |
| rogue | vanetza | DENM | certificate | 118 | 236 | 236 | 0 | 0 (-) |
| rust | python | CAM | certificate | 1145 | 1147 | 1147 | 0 | 0 (-) |
| rust | python | CAM | digest | 34 | 34 | 33 | 1 | 0 (-) |
| rust | python | DENM | certificate | 236 | 416 | 416 | 0 | 0 (-) |
| rust | rogue | CAM | certificate | 1157 | 1157 | 0 | 0 | 1157 (INCONSISTENT_CHAIN 1157) |
| rust | rogue | CAM | digest | 28 | 28 | 0 | 28 | 0 (-) |
| rust | rogue | DENM | certificate | 236 | 533 | 0 | 0 | 533 (INCONSISTENT_CHAIN 533) |
| rust | vanetza | CAM | certificate | 1161 | 1161 | 4 | 0 | 1157 (False_Signature 1157) |
| rust | vanetza | CAM | digest | 53 | 54 | 26 | 1 | 27 (False_Signature 27) |
| rust | vanetza | DENM | certificate | 242 | 360 | 360 | 0 | 0 (-) |
| vanetza | python | CAM | certificate | 1134 | 1136 | 1136 | 0 | 0 (-) |
| vanetza | python | CAM | digest | 47 | 47 | 47 | 0 | 0 (-) |
| vanetza | python | DENM | certificate | 118 | 356 | 356 | 0 | 0 (-) |
| vanetza | rogue | CAM | certificate | 1145 | 1145 | 0 | 0 | 1145 (INCONSISTENT_CHAIN 1145) |
| vanetza | rogue | CAM | digest | 42 | 42 | 0 | 42 | 0 (-) |
| vanetza | rogue | DENM | certificate | 118 | 476 | 0 | 0 | 476 (INCONSISTENT_CHAIN 476) |
| vanetza | rust | CAM | certificate | 1149 | 1150 | 1150 | 0 | 0 (-) |
| vanetza | rust | CAM | digest | 65 | 66 | 66 | 0 | 0 (-) |
| vanetza | rust | DENM | certificate | 121 | 362 | 362 | 0 | 0 (-) |

| Sender | Receiver | Facility message | Sent (signed) | Verified | Delivered | CAMs verified, not delivered |
|---|---|---|---:|---:|---:|---:|
| python | rust | CAM | 1119 | 1119 | 1119 | 0 |
| python | rust | DENM | 117 | 407 | 117 | - |
| python | vanetza | CAM | 1119 | 6 | 6 | 0 |
| python | vanetza | DENM | 117 | 351 | 351 | - |
| rogue | vanetza | DENM | 118 | 236 | 236 | - |
| rust | python | CAM | 1179 | 1180 | 1180 | 0 |
| rust | python | DENM | 236 | 416 | 118 | - |
| rust | vanetza | CAM | 1214 | 30 | 30 | 0 |
| rust | vanetza | DENM | 242 | 360 | 360 | - |
| vanetza | python | CAM | 1181 | 1183 | 1183 | 0 |
| vanetza | python | DENM | 118 | 356 | 118 | - |
| vanetza | rust | CAM | 1214 | 1216 | 1216 | 0 |
| vanetza | rust | DENM | 121 | 362 | 121 | - |
