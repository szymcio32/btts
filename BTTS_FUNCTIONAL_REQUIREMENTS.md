# BTTS Bot — Functional Requirements

## 1. Application Overview

**Purpose:** Fully automated soccer betting bot that places and manages limit orders on the "Both Teams to Score — No" prediction market on the Polymarket CLOB platform. The bot monitors multiple soccer leagues, identifies pre-game BTTS markets, analyses orderbook depth to determine optimal entry prices, accumulates bought positions through partial fills, and exits them before or at kickoff to capture a spread profit.

**Key Features:**

- Config-driven league and bet-parameter selection
- Daily automated market discovery
- Three-case orderbook bid-depth analysis to set buy price
- Order lifecycle management (buy → fill → sell)
- Game-start order re-creation

**Target User:** Automated trader / bettor with a funded Polymarket proxy wallet and API credentials.

---

## 2. Functional Requirements

---

### Area 1 — Configuration System

**FR-001**  
**Title:** YAML Configuration Loading  
**Description:** The system must load all operational parameters from a YAML configuration file at startup. The path defaults to `config_btts.yaml` in the project root and can be overridden via a CLI argument.  
---

**FR-002**  
**Title:** League Configuration Parameters  
**Description:** The config must support a list of soccer leagues, each identified by a Polymarket league abbreviation
---

**FR-003**  
**Title:** Bet Execution Parameters  
**Description:** A dedicated `btts` section in the config controls all order-sizing and spread parameters.  
---

**FR-004**  
**Title:** Liquidity Analysis Thresholds  
**Description:** A `liquidity` section in the config provides the three numeric thresholds used by the bid-depth analysis algorithm to determine the optimal buy price.  
---

**FR-005**  
**Title:** Timing and Scheduling Parameters  
**Description:** A `timing` section in the config controls when daily market fetches happen and how frequently the timer loop runs.  
---

**FR-006**  
**Title:** Logging and Persistence Configuration  
**Description:** A `logging` section in the config specifies file paths for the system log
---

### Area 2 — Authentication & Client Initialization

**FR-007**  
**Title:** Polymarket CLOB Client Initialization  
**Description:** On startup the system must initialize an authenticated CLOB client using private key and proxy wallet address from environment variables.  
---

### Area 3 — Soccer Market Selection

**FR-008**  
**Title:** Daily Market Discovery  
**Description:** Once per day at a configured UTC hour, the system must fetch all BTTS markets for all configured leagues from the json file 
---

**FR-009**  
**Title:** Token Selection — "No" Outcome  
**Description:** The system must always trade the "No" BTTS token
---

**FR-010**  
**Title:** Skip Already-Processed Markets  
**Description:** If a buy order has already been placed for a market in a previous run, the system must not place a duplicate buy order.  
---

### Area 4 — Betting Strategy — Buy Pricing (Liquidity Analysis)

**FR-011**  
**Title:** Orderbook Bid-Depth Analysis  
**Description:** Before placing a buy order, the system must analyse the top three bid levels of the "No" token's orderbook to determine the optimal limit buy price.  
---

**FR-012**  
**Title:** Sell Price Derivation  
**Description:** The limit sell price for a position must be set as `buy_price + price_diff`, capped at 0.99.  
---

### Area 5 — Bet Execution

**FR-013**  
**Title:** Limit Buy Order Placement  
**Description:** After determining the buy price, the system must place a limit BUY order with expiration time (defined in the config) on the Polymarket platform for the "No" token with the configured share amount.
---

**FR-014**  
**Title:** Incremental Fill Accumulation and Sell Order Placement  
**Description:** A new limit SELL order must be placed for every batch of buy shares that reaches the minimum order size (5 shares)
---

### Area 7 — Game Start Handling

**FR-017**  
**Title:** Consolidate and Re-Create Sell Orders Before Game Start  
**Description:** The system must cancel all unfilled sell orders close to kickoff (configurable in config) and re-create a single consolidated sell at the breakeven (buy) price to maximize fill probability. 

**FR-018**  
**Title:** Primary Game-Start Sell Re-Creation 
**Description:** When the game starts, the Polymarket automatically cancels all open orders. The system must detect this and re-place not filled sell orders for all filled buy positions with the buy price. The system after placing a sell order it should also make sure after 1 minute if the order was plaed successfully, if not it should retry placing the sell order.
---

### Area 9 — Position Reconciliation

**FR-026**  
**Title:** Daily Market Fetch Scheduling  
**Description:** Markets must be fetched once immediately on startup, then once daily at the configured UTC hour.  
---

### Area 13 — Error Handling & Safeguards

**FR-033**  
**Title:** API Failure Handling — Non-Fatal  
**Description:** Individual API call failures (orderbook fetch, order placement) must not crash the bot.  
---

**FR-034**  
**Title:** Duplicate Buy Order Prevention  
**Description:** The system must never place more than one buy order per market
---

**FR-035**  
**Title:** Duplicate Sell Order Prevention  
**Description:** New sell orders must not be created if existing LIVE sell orders already cover the position.  
---

**FR-037**  
**Title:** Structured Logging to File and Console  
**Description:** All operational events must be logged with timestamp, level, and logger name, to both a log file and the console simultaneously.  
---

## 3. User Flows

### Flow A — Normal Lifecycle (Buy → Fill → Sell → Fill)

1. Bot starts → initial market fetch (FR-008, FR-026).
2. Buy orders placed at liquidity-analysed prices (FR-011, FR-013).
3. Fill accumulated (FR-014) → sell order placed.
5. Sell order fills → position fully exited.

### Flow B — Pre-Kickoff Exit

1. 10 min (configurable) before kickoff: the system cancels all unfilled sells and re-creates a single consolidated sell at the buy price (FR-017) to improve fill probability at the last moment.

### Flow C — Game Start Recovery

1. At kickoff, Polymarket automatically cancels all open orders → system should detect this (FR-018) and re-places sell orders for all filled buy positions at the buy price to preserve the position.
2. The system should check after 1 minute if the sell order was placed successfully, and if not, it should retry placing the sell order until successful.

---

## 4. Example of condiguration file structure

```yaml
leagues:
    name: 'Premier League'
    leagueAbbreviation: 'epl'
    name: 'La Liga'
    leagueAbbreviation: 'lal'
    name: 'Bundesliga'
    leagueAbbreviation: 'bun'
    name: 'Serie A'
    leagueAbbreviation: 'sea'
    name: 'Ligue 1'
    leagueAbbreviation: 'fl1'

btts:
  side: 'No' # bet on "No" token (index 1 of clobTokenIds)
  size: 30 # order size
  price_diff: 0.02 # sell price = buy order price + this offset
  min_order_size: 5 # minimum shares for a limit sell order (Polymarket minimum)
  cancel_buy_before_start_min: 60 # cancel unfilled buy orders N min before game start
  cancel_sell_before_start_min: 10 # cancel unfilled sell orders N min before game start

liquidity:
  # Three-level bid analysis — evaluated top-to-bottom on the orderbook.
  # Case C: sum of top-3 bid liquidities < low_liquidity_total → order at L3 price - tick_offset
  # Case B: level-3 liquidity > high_liquidity_l3 → order at L2 price (aggressive, deep book)
  # Case A: otherwise → order at L3 price (standard)
  low_liquidity_total: 500 # USD threshold — total across 3 levels
  high_liquidity_l3: 8000 # USD threshold — level 3 alone
  tick_offset: 0.01 # price decrement for Case C

timing:
  fetch_hour: 23 # hour (UTC) to fetch markets daily

logging:
  log_file: 'logs/btts_bot.log'
```

## 5. Example of json file with all games and markets for a given day

```json
{
  "date": "2026-03-23",
  "games": [
    {
      "id": "230411",
      "league": "aus",
      "league_prefix": "aus",
      "home_team": "Sydney FC",
      "away_team": "Newcastle United Jets FC",
      "home_abbr": "syd",
      "away_abbr": "new",
      "kickoff_utc": "2026-03-22T04:00:00Z",
      "slug": "aus-syd-new-2026-03-22-more-markets",
      "polymarket": {
        "slug": "aus-syd-new-2026-03-22-more-markets",
        "event_id": "230411",
        "condition_id": "0xf198b3f4eea3bbcf6b4bc988208821fa34c29e3fbe087ba32bc8b67485c77659",
        "tokens": {
          "Sydney FC (-1.5)": {
            "yes": "112591576184318972487738983051314088387382048086017884880582143242622181654951",
            "no": "78284002500130386295728932442310590118989237090776961733159073138983939386106"
          },
          "Newcastle United Jets FC (-1.5)": {
            "yes": "115138734545370140765953061999024083465653845491211723618842922159592323268841",
            "no": "11470417868733370502101072067176023792628548961845081102877923577791261153684"
          },
          "Newcastle United Jets FC (-2.5)": {
            "yes": "71177295275479948880911905215876309863308619128297232945952862785026045163056",
            "no": "59577140359701458629035880926018071845609669216417789809468016923982338327033"
          },
          "O/U 1.5": {
            "yes": "59514403104510099926453705032656747453739499175933812664632316618893243702163",
            "no": "4781532024929262134682394901091186880794643385453372497378055899537284345174"
          },
          "O/U 2.5": {
            "yes": "60652988880229604769169399184306691511923760696767280243510140720438493364636",
            "no": "70578430570810503076314990045600698314279951730340568404764420907795328919979"
          },
          "Sydney FC (-2.5)": {
            "yes": "108162825654443510095972925690525342361699158614236181408973124665356496794118",
            "no": "1511206110217873287028630865557428364039961954883634046716981109437658320800"
          },
          "O/U 3.5": {
            "yes": "79815921244845562972929839336727201700719878894508659123700106203615583290441",
            "no": "54228123318354455558420663373402659222783202826190910060864971282424166255858"
          },
          "O/U 4.5": {
            "yes": "44302689136003676864534691479203423168399429304176269641758147839761886067883",
            "no": "1515488430021301291978960428080436587672406165148550321055783713692193976022"
          },
          "Both Teams to Score": {
            "yes": "8918611046959331575936068373532483441698893850425010843952859682644376342373",
            "no": "38943220449660990924636562233770237852358139963570887601820621206851979136964"
          }
        },
        "markets": [
          {
            "condition_id": "0xf198b3f4eea3bbcf6b4bc988208821fa34c29e3fbe087ba32bc8b67485c77659",
            "question": "Spread: Sydney FC (-1.5)",
            "outcome_label": "Sydney FC (-1.5)",
            "market_type": "spreads",
            "outcome_prices": [
              "0",
              "1"
            ],
            "token_ids": [
              "112591576184318972487738983051314088387382048086017884880582143242622181654951",
              "78284002500130386295728932442310590118989237090776961733159073138983939386106"
            ]
          },
          {
            "condition_id": "0x961b49288de87f678df94cdd3708f6daabd9eb6f9054ea1039b35b5ff1eb7f55",
            "question": "Spread: Newcastle United Jets FC (-1.5)",
            "outcome_label": "Newcastle United Jets FC (-1.5)",
            "market_type": "spreads",
            "outcome_prices": [
              "0",
              "1"
            ],
            "token_ids": [
              "115138734545370140765953061999024083465653845491211723618842922159592323268841",
              "11470417868733370502101072067176023792628548961845081102877923577791261153684"
            ]
          },
          {
            "condition_id": "0x7c48b3132d8020b2d866b32dd4349d44891b63ad53592be7d1a980a65f8c66e7",
            "question": "Spread: Newcastle United Jets FC (-2.5)",
            "outcome_label": "Newcastle United Jets FC (-2.5)",
            "market_type": "spreads",
            "outcome_prices": [
              "0",
              "1"
            ],
            "token_ids": [
              "71177295275479948880911905215876309863308619128297232945952862785026045163056",
              "59577140359701458629035880926018071845609669216417789809468016923982338327033"
            ]
          },
          {
            "condition_id": "0x4ec6eeac96222beef6379de1215b99d83f2ef2474b926563e54ad4cffec16678",
            "question": "Sydney FC vs. Newcastle United Jets FC: O/U 1.5",
            "outcome_label": "O/U 1.5",
            "market_type": "totals",
            "outcome_prices": [
              "1",
              "0"
            ],
            "token_ids": [
              "59514403104510099926453705032656747453739499175933812664632316618893243702163",
              "4781532024929262134682394901091186880794643385453372497378055899537284345174"
            ]
          },
          {
            "condition_id": "0xd9be5ae6282aca5bc58a80f9aec9fa70d74c1caa5c8350e2cc304238f39230c0",
            "question": "Sydney FC vs. Newcastle United Jets FC: O/U 2.5",
            "outcome_label": "O/U 2.5",
            "market_type": "totals",
            "outcome_prices": [
              "1",
              "0"
            ],
            "token_ids": [
              "60652988880229604769169399184306691511923760696767280243510140720438493364636",
              "70578430570810503076314990045600698314279951730340568404764420907795328919979"
            ]
          },
          {
            "condition_id": "0x2c69a69a525541240cc98b79d6af01b3b5c8a17e238ca10090a2a9317e7655bf",
            "question": "Spread: Sydney FC (-2.5)",
            "outcome_label": "Sydney FC (-2.5)",
            "market_type": "spreads",
            "outcome_prices": [
              "0",
              "1"
            ],
            "token_ids": [
              "108162825654443510095972925690525342361699158614236181408973124665356496794118",
              "1511206110217873287028630865557428364039961954883634046716981109437658320800"
            ]
          },
          {
            "condition_id": "0xf188b98780cf4ad5ea2550250796752f186f0d9ec53ce4fdc1f3d9e90db7719e",
            "question": "Sydney FC vs. Newcastle United Jets FC: O/U 3.5",
            "outcome_label": "O/U 3.5",
            "market_type": "totals",
            "outcome_prices": [
              "0",
              "1"
            ],
            "token_ids": [
              "79815921244845562972929839336727201700719878894508659123700106203615583290441",
              "54228123318354455558420663373402659222783202826190910060864971282424166255858"
            ]
          },
          {
            "condition_id": "0x99c138de094ecba8d639a7024cce8750444b6a972a8974dc7e1918cfe30fb238",
            "question": "Sydney FC vs. Newcastle United Jets FC: O/U 4.5",
            "outcome_label": "O/U 4.5",
            "market_type": "totals",
            "outcome_prices": [
              "0",
              "1"
            ],
            "token_ids": [
              "44302689136003676864534691479203423168399429304176269641758147839761886067883",
              "1515488430021301291978960428080436587672406165148550321055783713692193976022"
            ]
          },
          {
            "condition_id": "0x176c4a43a7098b611952f02e4e9206570af4659fd308a6a9137fce016e63cf78",
            "question": "Sydney FC vs. Newcastle United Jets FC: Both Teams to Score",
            "outcome_label": "Both Teams to Score",
            "market_type": "both_teams_to_score",
            "outcome_prices": [
              "1",
              "0"
            ],
            "token_ids": [
              "8918611046959331575936068373532483441698893850425010843952859682644376342373",
              "38943220449660990924636562233770237852358139963570887601820621206851979136964"
            ]
          }
        ]
      },
      "polls": {
        "76": {
          "fired": true,
          "scheduled_utc": "2026-03-22T05:16:00Z",
          "status": "error"
        }
      },
      "snapshots": [
        {
          "game_id": "230411",
          "league": "aus",
          "home_team": "Sydney FC",
          "away_team": "Newcastle United Jets FC",
          "home_abbr": "syd",
          "away_abbr": "new",
          "score": {
            "home": null,
            "away": null
          },
          "minute": null,
          "status": "",
          "status_more": "",
          "polymarket": {
            "slug": "aus-syd-new-2026-03-22-more-markets",
            "event_id": "230411",
            "condition_id": "0xf198b3f4eea3bbcf6b4bc988208821fa34c29e3fbe087ba32bc8b67485c77659",
            "tokens": {
              "Sydney FC (-1.5)": {
                "yes": "112591576184318972487738983051314088387382048086017884880582143242622181654951",
                "no": "78284002500130386295728932442310590118989237090776961733159073138983939386106"
              },
              "Newcastle United Jets FC (-1.5)": {
                "yes": "115138734545370140765953061999024083465653845491211723618842922159592323268841",
                "no": "11470417868733370502101072067176023792628548961845081102877923577791261153684"
              },
              "Newcastle United Jets FC (-2.5)": {
                "yes": "71177295275479948880911905215876309863308619128297232945952862785026045163056",
                "no": "59577140359701458629035880926018071845609669216417789809468016923982338327033"
              },
              "O/U 1.5": {
                "yes": "59514403104510099926453705032656747453739499175933812664632316618893243702163",
                "no": "4781532024929262134682394901091186880794643385453372497378055899537284345174"
              },
              "O/U 2.5": {
                "yes": "60652988880229604769169399184306691511923760696767280243510140720438493364636",
                "no": "70578430570810503076314990045600698314279951730340568404764420907795328919979"
              },
              "Sydney FC (-2.5)": {
                "yes": "108162825654443510095972925690525342361699158614236181408973124665356496794118",
                "no": "1511206110217873287028630865557428364039961954883634046716981109437658320800"
              },
              "O/U 3.5": {
                "yes": "79815921244845562972929839336727201700719878894508659123700106203615583290441",
                "no": "54228123318354455558420663373402659222783202826190910060864971282424166255858"
              },
              "O/U 4.5": {
                "yes": "44302689136003676864534691479203423168399429304176269641758147839761886067883",
                "no": "1515488430021301291978960428080436587672406165148550321055783713692193976022"
              },
              "Both Teams to Score": {
                "yes": "8918611046959331575936068373532483441698893850425010843952859682644376342373",
                "no": "38943220449660990924636562233770237852358139963570887601820621206851979136964"
              }
            },
            "markets": [
              {
                "condition_id": "0xf198b3f4eea3bbcf6b4bc988208821fa34c29e3fbe087ba32bc8b67485c77659",
                "question": "Spread: Sydney FC (-1.5)",
                "outcome_label": "Sydney FC (-1.5)",
                "market_type": "spreads",
                "outcome_prices": [
                  "0",
                  "1"
                ],
                "token_ids": [
                  "112591576184318972487738983051314088387382048086017884880582143242622181654951",
                  "78284002500130386295728932442310590118989237090776961733159073138983939386106"
                ]
              },
              {
                "condition_id": "0x961b49288de87f678df94cdd3708f6daabd9eb6f9054ea1039b35b5ff1eb7f55",
                "question": "Spread: Newcastle United Jets FC (-1.5)",
                "outcome_label": "Newcastle United Jets FC (-1.5)",
                "market_type": "spreads",
                "outcome_prices": [
                  "0",
                  "1"
                ],
                "token_ids": [
                  "115138734545370140765953061999024083465653845491211723618842922159592323268841",
                  "11470417868733370502101072067176023792628548961845081102877923577791261153684"
                ]
              },
              {
                "condition_id": "0x7c48b3132d8020b2d866b32dd4349d44891b63ad53592be7d1a980a65f8c66e7",
                "question": "Spread: Newcastle United Jets FC (-2.5)",
                "outcome_label": "Newcastle United Jets FC (-2.5)",
                "market_type": "spreads",
                "outcome_prices": [
                  "0",
                  "1"
                ],
                "token_ids": [
                  "71177295275479948880911905215876309863308619128297232945952862785026045163056",
                  "59577140359701458629035880926018071845609669216417789809468016923982338327033"
                ]
              },
              {
                "condition_id": "0x4ec6eeac96222beef6379de1215b99d83f2ef2474b926563e54ad4cffec16678",
                "question": "Sydney FC vs. Newcastle United Jets FC: O/U 1.5",
                "outcome_label": "O/U 1.5",
                "market_type": "totals",
                "outcome_prices": [
                  "1",
                  "0"
                ],
                "token_ids": [
                  "59514403104510099926453705032656747453739499175933812664632316618893243702163",
                  "4781532024929262134682394901091186880794643385453372497378055899537284345174"
                ]
              },
              {
                "condition_id": "0xd9be5ae6282aca5bc58a80f9aec9fa70d74c1caa5c8350e2cc304238f39230c0",
                "question": "Sydney FC vs. Newcastle United Jets FC: O/U 2.5",
                "outcome_label": "O/U 2.5",
                "market_type": "totals",
                "outcome_prices": [
                  "1",
                  "0"
                ],
                "token_ids": [
                  "60652988880229604769169399184306691511923760696767280243510140720438493364636",
                  "70578430570810503076314990045600698314279951730340568404764420907795328919979"
                ]
              },
              {
                "condition_id": "0x2c69a69a525541240cc98b79d6af01b3b5c8a17e238ca10090a2a9317e7655bf",
                "question": "Spread: Sydney FC (-2.5)",
                "outcome_label": "Sydney FC (-2.5)",
                "market_type": "spreads",
                "outcome_prices": [
                  "0",
                  "1"
                ],
                "token_ids": [
                  "108162825654443510095972925690525342361699158614236181408973124665356496794118",
                  "1511206110217873287028630865557428364039961954883634046716981109437658320800"
                ]
              },
              {
                "condition_id": "0xf188b98780cf4ad5ea2550250796752f186f0d9ec53ce4fdc1f3d9e90db7719e",
                "question": "Sydney FC vs. Newcastle United Jets FC: O/U 3.5",
                "outcome_label": "O/U 3.5",
                "market_type": "totals",
                "outcome_prices": [
                  "0",
                  "1"
                ],
                "token_ids": [
                  "79815921244845562972929839336727201700719878894508659123700106203615583290441",
                  "54228123318354455558420663373402659222783202826190910060864971282424166255858"
                ]
              },
              {
                "condition_id": "0x99c138de094ecba8d639a7024cce8750444b6a972a8974dc7e1918cfe30fb238",
                "question": "Sydney FC vs. Newcastle United Jets FC: O/U 4.5",
                "outcome_label": "O/U 4.5",
                "market_type": "totals",
                "outcome_prices": [
                  "0",
                  "1"
                ],
                "token_ids": [
                  "44302689136003676864534691479203423168399429304176269641758147839761886067883",
                  "1515488430021301291978960428080436587672406165148550321055783713692193976022"
                ]
              },
              {
                "condition_id": "0x176c4a43a7098b611952f02e4e9206570af4659fd308a6a9137fce016e63cf78",
                "question": "Sydney FC vs. Newcastle United Jets FC: Both Teams to Score",
                "outcome_label": "Both Teams to Score",
                "market_type": "both_teams_to_score",
                "outcome_prices": [
                  "1",
                  "0"
                ],
                "token_ids": [
                  "8918611046959331575936068373532483441698893850425010843952859682644376342373",
                  "38943220449660990924636562233770237852358139963570887601820621206851979136964"
                ]
              }
            ]
          },
          "polled_at": "2026-03-22T12:21:13Z",
          "poll_offset_minutes": 76
        }
      ]
    },
    {
      "id": "230410",
      "league": "aus",
      "league_prefix": "aus",
      "home_team": "Perth Glory FC",
      "away_team": "Melbourne City FC",
      "home_abbr": "per",
      "away_abbr": "mct",
      "kickoff_utc": "2026-03-22T08:00:00Z",
      "slug": "aus-per-mct-2026-03-22-more-markets",
      "polymarket": {
        "slug": "aus-per-mct-2026-03-22-more-markets",
        "event_id": "230410",
        "condition_id": "0x2f7dd992affab16216f17f9743710721e252527856d5e344841e28d72b0bc15a",
        "tokens": {
          "Perth Glory FC (-1.5)": {
            "yes": "12223275654467540850097193624023278147011938386627287029519768416127521743382",
            "no": "103282592782793955587988122688203041915784224488453967799115163937552883281399"
          },
          "Melbourne City FC (-1.5)": {
            "yes": "44233911824544066649134594100992215501618913138727206294645756352641328109234",
            "no": "19274630202437794566885785213668146040818005333687360136639820229051087174357"
          },
          "Perth Glory FC (-2.5)": {
            "yes": "71031749736632452749423744069788431903094500546143449208699194267313588597735",
            "no": "37294467350637031218398109712680324241427656406651976209103625970414797920647"
          },
          "Melbourne City FC (-2.5)": {
            "yes": "50213546272506838937243231707089515667989618300738556889648672217824174636306",
            "no": "66270172696308693294267853400285426736243736751617841990201221618495742594771"
          },
          "O/U 1.5": {
            "yes": "61871418320065143986212198342527860290972789134563558668614981487884950075994",
            "no": "82440568899784107601851540415544664221129478450896328711218883702170855280470"
          },
          "O/U 2.5": {
            "yes": "114318768189180772381774867216685547367829215128468550910445325727726919637638",
            "no": "86745737644772423002212352348325523673634514128120387210072749114332710731824"
          },
          "O/U 3.5": {
            "yes": "98529789112595658152912885636326037495056184356658766048494669255354783013075",
            "no": "74018620019711843021268374936583525600128414552981544277345928319040255779284"
          },
          "O/U 4.5": {
            "yes": "51686080358617089751907521298100738176373566391672030560448774150478305491114",
            "no": "73303365526952598678371481884594425788369392358916219880349175331065345551507"
          },
          "Both Teams to Score": {
            "yes": "27616829082222575936864494896529385079229442498551223075008754974589575391437",
            "no": "88064229864554389435447283410192852195279784205772263239814482492744117734470"
          }
        },
        "markets": [
          {
            "condition_id": "0x2f7dd992affab16216f17f9743710721e252527856d5e344841e28d72b0bc15a",
            "question": "Spread: Perth Glory FC (-1.5)",
            "outcome_label": "Perth Glory FC (-1.5)",
            "market_type": "spreads",
            "outcome_prices": [
              "0.0005",
              "0.9995"
            ],
            "token_ids": [
              "12223275654467540850097193624023278147011938386627287029519768416127521743382",
              "103282592782793955587988122688203041915784224488453967799115163937552883281399"
            ]
          },
          {
            "condition_id": "0x7fef71a9b74213437275429d17609a47938429f88bc920707798f1cb6b710e00",
            "question": "Spread: Melbourne City FC (-1.5)",
            "outcome_label": "Melbourne City FC (-1.5)",
            "market_type": "spreads",
            "outcome_prices": [
              "0.0005",
              "0.9995"
            ],
            "token_ids": [
              "44233911824544066649134594100992215501618913138727206294645756352641328109234",
              "19274630202437794566885785213668146040818005333687360136639820229051087174357"
            ]
          },
          {
            "condition_id": "0xa98143e59373c8c7307df2d8afa31a1128fb80b6fd68a205a21b5e2ba2d2f806",
            "question": "Spread: Perth Glory FC (-2.5)",
            "outcome_label": "Perth Glory FC (-2.5)",
            "market_type": "spreads",
            "outcome_prices": [
              "0.0005",
              "0.9995"
            ],
            "token_ids": [
              "71031749736632452749423744069788431903094500546143449208699194267313588597735",
              "37294467350637031218398109712680324241427656406651976209103625970414797920647"
            ]
          },
          {
            "condition_id": "0x5c95d9ddd3a05de80edd8b248287176cdcb4edb736f263ef2fa6fab95bc9249d",
            "question": "Spread: Melbourne City FC (-2.5)",
            "outcome_label": "Melbourne City FC (-2.5)",
            "market_type": "spreads",
            "outcome_prices": [
              "0.0005",
              "0.9995"
            ],
            "token_ids": [
              "50213546272506838937243231707089515667989618300738556889648672217824174636306",
              "66270172696308693294267853400285426736243736751617841990201221618495742594771"
            ]
          },
          {
            "condition_id": "0x7fb5434e2d27edfb8b5a7af79c341405ffccf690e9eb992eadb3bc8d584aaeba",
            "question": "Perth Glory FC vs. Melbourne City FC: O/U 1.5",
            "outcome_label": "O/U 1.5",
            "market_type": "totals",
            "outcome_prices": [
              "0.9995",
              "0.0005"
            ],
            "token_ids": [
              "61871418320065143986212198342527860290972789134563558668614981487884950075994",
              "82440568899784107601851540415544664221129478450896328711218883702170855280470"
            ]
          },
          {
            "condition_id": "0x9effcee13bc7c7aa9ea21451f578ea10b5e09a81a7dc0921e734fc41147af250",
            "question": "Perth Glory FC vs. Melbourne City FC: O/U 2.5",
            "outcome_label": "O/U 2.5",
            "market_type": "totals",
            "outcome_prices": [
              "0.0005",
              "0.9995"
            ],
            "token_ids": [
              "114318768189180772381774867216685547367829215128468550910445325727726919637638",
              "86745737644772423002212352348325523673634514128120387210072749114332710731824"
            ]
          },
          {
            "condition_id": "0xa65e175845fd3c23c4a5696155c5dc9fea9f08ab5d2f015494b2578580cf0c95",
            "question": "Perth Glory FC vs. Melbourne City FC: O/U 3.5",
            "outcome_label": "O/U 3.5",
            "market_type": "totals",
            "outcome_prices": [
              "0.0005",
              "0.9995"
            ],
            "token_ids": [
              "98529789112595658152912885636326037495056184356658766048494669255354783013075",
              "74018620019711843021268374936583525600128414552981544277345928319040255779284"
            ]
          },
          {
            "condition_id": "0x4ae4a0cd3756ed2d87b00b3cb24a8d15842e61cb0dc933e1981156502927256c",
            "question": "Perth Glory FC vs. Melbourne City FC: O/U 4.5",
            "outcome_label": "O/U 4.5",
            "market_type": "totals",
            "outcome_prices": [
              "0.0005",
              "0.9995"
            ],
            "token_ids": [
              "51686080358617089751907521298100738176373566391672030560448774150478305491114",
              "73303365526952598678371481884594425788369392358916219880349175331065345551507"
            ]
          },
          {
            "condition_id": "0x667ac51cf971332a6e1e19a731d87fc446645612e3654d7ce13468c04e5aa877",
            "question": "Perth Glory FC vs. Melbourne City FC: Both Teams to Score",
            "outcome_label": "Both Teams to Score",
            "market_type": "both_teams_to_score",
            "outcome_prices": [
              "0.9995",
              "0.0005"
            ],
            "token_ids": [
              "27616829082222575936864494896529385079229442498551223075008754974589575391437",
              "88064229864554389435447283410192852195279784205772263239814482492744117734470"
            ]
          }
        ]
      },
      "polls": {
        "76": {
          "fired": true,
          "scheduled_utc": "2026-03-22T09:16:00Z",
          "status": "ok"
        }
      },
      "snapshots": [
        {
          "game_id": "230410",
          "league": "aus",
          "home_team": "Perth Glory FC",
          "away_team": "Melbourne City FC",
          "home_abbr": "per",
          "away_abbr": "mct",
          "score": {
            "home": null,
            "away": null
          },
          "minute": null,
          "status": "",
          "status_more": "",
          "polymarket": {
            "slug": "aus-per-mct-2026-03-22-more-markets",
            "event_id": "230410",
            "condition_id": "0x2f7dd992affab16216f17f9743710721e252527856d5e344841e28d72b0bc15a",
            "tokens": {
              "Perth Glory FC (-1.5)": {
                "yes": "12223275654467540850097193624023278147011938386627287029519768416127521743382",
                "no": "103282592782793955587988122688203041915784224488453967799115163937552883281399"
              },
              "Melbourne City FC (-1.5)": {
                "yes": "44233911824544066649134594100992215501618913138727206294645756352641328109234",
                "no": "19274630202437794566885785213668146040818005333687360136639820229051087174357"
              },
              "Perth Glory FC (-2.5)": {
                "yes": "71031749736632452749423744069788431903094500546143449208699194267313588597735",
                "no": "37294467350637031218398109712680324241427656406651976209103625970414797920647"
              },
              "Melbourne City FC (-2.5)": {
                "yes": "50213546272506838937243231707089515667989618300738556889648672217824174636306",
                "no": "66270172696308693294267853400285426736243736751617841990201221618495742594771"
              },
              "O/U 1.5": {
                "yes": "61871418320065143986212198342527860290972789134563558668614981487884950075994",
                "no": "82440568899784107601851540415544664221129478450896328711218883702170855280470"
              },
              "O/U 2.5": {
                "yes": "114318768189180772381774867216685547367829215128468550910445325727726919637638",
                "no": "86745737644772423002212352348325523673634514128120387210072749114332710731824"
              },
              "O/U 3.5": {
                "yes": "98529789112595658152912885636326037495056184356658766048494669255354783013075",
                "no": "74018620019711843021268374936583525600128414552981544277345928319040255779284"
              },
              "O/U 4.5": {
                "yes": "51686080358617089751907521298100738176373566391672030560448774150478305491114",
                "no": "73303365526952598678371481884594425788369392358916219880349175331065345551507"
              },
              "Both Teams to Score": {
                "yes": "27616829082222575936864494896529385079229442498551223075008754974589575391437",
                "no": "88064229864554389435447283410192852195279784205772263239814482492744117734470"
              }
            },
            "markets": [
              {
                "condition_id": "0x2f7dd992affab16216f17f9743710721e252527856d5e344841e28d72b0bc15a",
                "question": "Spread: Perth Glory FC (-1.5)",
                "outcome_label": "Perth Glory FC (-1.5)",
                "market_type": "spreads",
                "outcome_prices": [
                  "0.0005",
                  "0.9995"
                ],
                "token_ids": [
                  "12223275654467540850097193624023278147011938386627287029519768416127521743382",
                  "103282592782793955587988122688203041915784224488453967799115163937552883281399"
                ]
              },
              {
                "condition_id": "0x7fef71a9b74213437275429d17609a47938429f88bc920707798f1cb6b710e00",
                "question": "Spread: Melbourne City FC (-1.5)",
                "outcome_label": "Melbourne City FC (-1.5)",
                "market_type": "spreads",
                "outcome_prices": [
                  "0.0005",
                  "0.9995"
                ],
                "token_ids": [
                  "44233911824544066649134594100992215501618913138727206294645756352641328109234",
                  "19274630202437794566885785213668146040818005333687360136639820229051087174357"
                ]
              },
              {
                "condition_id": "0xa98143e59373c8c7307df2d8afa31a1128fb80b6fd68a205a21b5e2ba2d2f806",
                "question": "Spread: Perth Glory FC (-2.5)",
                "outcome_label": "Perth Glory FC (-2.5)",
                "market_type": "spreads",
                "outcome_prices": [
                  "0.0005",
                  "0.9995"
                ],
                "token_ids": [
                  "71031749736632452749423744069788431903094500546143449208699194267313588597735",
                  "37294467350637031218398109712680324241427656406651976209103625970414797920647"
                ]
              },
              {
                "condition_id": "0x5c95d9ddd3a05de80edd8b248287176cdcb4edb736f263ef2fa6fab95bc9249d",
                "question": "Spread: Melbourne City FC (-2.5)",
                "outcome_label": "Melbourne City FC (-2.5)",
                "market_type": "spreads",
                "outcome_prices": [
                  "0.0005",
                  "0.9995"
                ],
                "token_ids": [
                  "50213546272506838937243231707089515667989618300738556889648672217824174636306",
                  "66270172696308693294267853400285426736243736751617841990201221618495742594771"
                ]
              },
              {
                "condition_id": "0x7fb5434e2d27edfb8b5a7af79c341405ffccf690e9eb992eadb3bc8d584aaeba",
                "question": "Perth Glory FC vs. Melbourne City FC: O/U 1.5",
                "outcome_label": "O/U 1.5",
                "market_type": "totals",
                "outcome_prices": [
                  "0.9995",
                  "0.0005"
                ],
                "token_ids": [
                  "61871418320065143986212198342527860290972789134563558668614981487884950075994",
                  "82440568899784107601851540415544664221129478450896328711218883702170855280470"
                ]
              },
              {
                "condition_id": "0x9effcee13bc7c7aa9ea21451f578ea10b5e09a81a7dc0921e734fc41147af250",
                "question": "Perth Glory FC vs. Melbourne City FC: O/U 2.5",
                "outcome_label": "O/U 2.5",
                "market_type": "totals",
                "outcome_prices": [
                  "0.0005",
                  "0.9995"
                ],
                "token_ids": [
                  "114318768189180772381774867216685547367829215128468550910445325727726919637638",
                  "86745737644772423002212352348325523673634514128120387210072749114332710731824"
                ]
              },
              {
                "condition_id": "0xa65e175845fd3c23c4a5696155c5dc9fea9f08ab5d2f015494b2578580cf0c95",
                "question": "Perth Glory FC vs. Melbourne City FC: O/U 3.5",
                "outcome_label": "O/U 3.5",
                "market_type": "totals",
                "outcome_prices": [
                  "0.0005",
                  "0.9995"
                ],
                "token_ids": [
                  "98529789112595658152912885636326037495056184356658766048494669255354783013075",
                  "74018620019711843021268374936583525600128414552981544277345928319040255779284"
                ]
              },
              {
                "condition_id": "0x4ae4a0cd3756ed2d87b00b3cb24a8d15842e61cb0dc933e1981156502927256c",
                "question": "Perth Glory FC vs. Melbourne City FC: O/U 4.5",
                "outcome_label": "O/U 4.5",
                "market_type": "totals",
                "outcome_prices": [
                  "0.0005",
                  "0.9995"
                ],
                "token_ids": [
                  "51686080358617089751907521298100738176373566391672030560448774150478305491114",
                  "73303365526952598678371481884594425788369392358916219880349175331065345551507"
                ]
              },
              {
                "condition_id": "0x667ac51cf971332a6e1e19a731d87fc446645612e3654d7ce13468c04e5aa877",
                "question": "Perth Glory FC vs. Melbourne City FC: Both Teams to Score",
                "outcome_label": "Both Teams to Score",
                "market_type": "both_teams_to_score",
                "outcome_prices": [
                  "0.9995",
                  "0.0005"
                ],
                "token_ids": [
                  "27616829082222575936864494896529385079229442498551223075008754974589575391437",
                  "88064229864554389435447283410192852195279784205772263239814482492744117734470"
                ]
              }
            ]
          },
          "polled_at": "2026-03-22T12:21:10Z",
          "poll_offset_minutes": 76
        }
      ]
    }
  ]
}
```

## 6. Additional Notes
- the performance of the tool is not important, but the correctness and completeness of the data is
- UI is not needed since it's a bot that runs in the background