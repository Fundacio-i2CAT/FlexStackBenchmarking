### rogue-openssl

| Sender | Receiver | Message | Signer | Sent | Received | Verified | AT not yet known | Refused (report) |
|---|---|---|---|---:|---:|---:|---:|---|
| python | rogue | CAM | certificate | 539 | 539 | 0 | 0 | 539 (INCONSISTENT_CHAIN 539) |
| python | rogue | CAM | digest | 3 | 3 | 0 | 3 | 0 (-) |
| python | rogue | DENM | certificate | 58 | 250 | 0 | 0 | 250 (INCONSISTENT_CHAIN 250) |
| python | rust | CAM | certificate | 541 | 541 | 541 | 0 | 0 (-) |
| python | rust | CAM | digest | 9 | 9 | 9 | 0 | 0 (-) |
| python | rust | DENM | certificate | 58 | 192 | 192 | 0 | 0 (-) |
| python | vanetza | CAM | certificate | 541 | 541 | 1 | 0 | 540 (False_Signature 540) |
| python | vanetza | CAM | digest | 9 | 9 | 5 | 1 | 3 (False_Signature 3) |
| python | vanetza | DENM | certificate | 58 | 173 | 173 | 0 | 0 (-) |
| rogue | python | CAM | certificate | 553 | 555 | 0 | 0 | 555 (INCONSISTENT_CHAIN 555) |
| rogue | python | DENM | certificate | 57 | 192 | 0 | 0 | 192 (INCONSISTENT_CHAIN 192) |
| rogue | rust | CAM | certificate | 563 | 565 | 0 | 0 | 565 (InconsistentChain 565) |
| rogue | rust | DENM | certificate | 58 | 194 | 0 | 0 | 194 (InconsistentChain 194) |
| rogue | vanetza | CAM | certificate | 565 | 567 | 0 | 0 | 567 (False_Signature 567) |
| rogue | vanetza | DENM | certificate | 58 | 116 | 116 | 0 | 0 (-) |
| rust | python | CAM | certificate | 560 | 562 | 562 | 0 | 0 (-) |
| rust | python | CAM | digest | 21 | 21 | 20 | 1 | 0 (-) |
| rust | python | DENM | certificate | 116 | 210 | 210 | 0 | 0 (-) |
| rust | rogue | CAM | certificate | 571 | 571 | 0 | 0 | 571 (INCONSISTENT_CHAIN 571) |
| rust | rogue | CAM | digest | 15 | 15 | 0 | 15 | 0 (-) |
| rust | rogue | DENM | certificate | 116 | 268 | 0 | 0 | 268 (INCONSISTENT_CHAIN 268) |
| rust | vanetza | CAM | certificate | 576 | 576 | 5 | 0 | 571 (False_Signature 571) |
| rust | vanetza | CAM | digest | 40 | 40 | 25 | 1 | 14 (False_Signature 14) |
| rust | vanetza | DENM | certificate | 122 | 180 | 180 | 0 | 0 (-) |
| vanetza | python | CAM | certificate | 554 | 556 | 556 | 0 | 0 (-) |
| vanetza | python | CAM | digest | 27 | 27 | 27 | 0 | 0 (-) |
| vanetza | python | DENM | certificate | 58 | 168 | 168 | 0 | 0 (-) |
| vanetza | rogue | CAM | certificate | 566 | 567 | 0 | 0 | 567 (INCONSISTENT_CHAIN 567) |
| vanetza | rogue | CAM | digest | 21 | 21 | 0 | 21 | 0 (-) |
| vanetza | rogue | DENM | certificate | 58 | 228 | 0 | 0 | 228 (INCONSISTENT_CHAIN 228) |
| vanetza | rust | CAM | certificate | 569 | 571 | 571 | 0 | 0 (-) |
| vanetza | rust | CAM | digest | 45 | 45 | 45 | 0 | 0 (-) |
| vanetza | rust | DENM | certificate | 61 | 174 | 174 | 0 | 0 (-) |

| Sender | Receiver | Facility message | Sent (signed) | Verified | Delivered | CAMs verified, not delivered |
|---|---|---|---:|---:|---:|---:|
| python | rust | CAM | 550 | 550 | 550 | 0 |
| python | rust | DENM | 58 | 192 | 58 | - |
| python | vanetza | CAM | 550 | 6 | 6 | 0 |
| python | vanetza | DENM | 58 | 173 | 173 | - |
| rogue | vanetza | DENM | 58 | 116 | 116 | - |
| rust | python | CAM | 581 | 582 | 582 | 0 |
| rust | python | DENM | 116 | 210 | 58 | - |
| rust | vanetza | CAM | 616 | 30 | 30 | 0 |
| rust | vanetza | DENM | 122 | 180 | 180 | - |
| vanetza | python | CAM | 581 | 583 | 583 | 0 |
| vanetza | python | DENM | 58 | 168 | 58 | - |
| vanetza | rust | CAM | 614 | 616 | 616 | 0 |
| vanetza | rust | DENM | 61 | 174 | 61 | - |
