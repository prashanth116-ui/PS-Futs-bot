# V10.13 ICT FVG Strategy — Flow Diagrams

## 1. Master Strategy Flow

```mermaid
flowchart TD
    START([Session Start<br>4:00 ET]) --> LOAD[Load 3m Bars<br>Overnight + Session]
    LOAD --> FVG[Detect All FVGs<br>from overnight + RTH bars]
    FVG --> INDICATORS[Calculate Indicators<br>EMA 20/50, ADX 14, DI+/DI-]

    INDICATORS --> ENTRY_A{Entry Type A<br>Creation}
    INDICATORS --> ENTRY_B{Entry Type B<br>Retrace}
    INDICATORS --> ENTRY_C{Entry Type C<br>BOS + Retrace}

    ENTRY_A --> COLLECT[Collect All Valid Entries<br>Sort by Bar Index]
    ENTRY_B --> COLLECT
    ENTRY_C --> COLLECT

    COLLECT --> LOOP[/For Each Bar in Session/]
    LOOP --> MANAGE[Manage Active Trades<br>Trail Updates + Exit Checks]
    MANAGE --> GATES{Entry Gates}

    GATES -->|Pass| SIZE[Position Sizing<br>3 cts → 2 cts → 1 ct]
    GATES -->|Fail| LOOP

    SIZE --> OPEN[Open Trade<br>Entry + Stop + Targets]
    OPEN --> LOOP

    LOOP -->|EOD 16:00| EOD[Close All Remaining<br>at Market Close]
    EOD --> SUMMARY([Print Results])
```

## 2. Entry Type Decision Tree

```mermaid
flowchart TD
    FVG_DETECTED([FVG Detected]) --> TYPE{Where was<br>FVG created?}

    TYPE -->|During session bar| A[Entry A: CREATION<br>Enter immediately at FVG midpoint]
    TYPE -->|Before 9:30 AM| B1[Entry B1: OVERNIGHT RETRACE<br>Wait for price to retrace into FVG]
    TYPE -->|During RTH, 2+ bars ago| B2[Entry B2: INTRADAY RETRACE<br>Wait for price to retrace into FVG]
    TYPE -->|After BOS, within 5 bars| C[Entry C: BOS RETRACE<br>Wait for price to retrace into FVG]

    A --> A_DISP{Displacement<br>>= 3x avg body?}
    A_DISP -->|Yes| A_OVERRIDE[3x Override<br>ADX >= 10 only]
    A_DISP -->|No| A_FILTER[Hybrid Filter Check]
    A_OVERRIDE --> VALID([Valid Entry])

    B1 --> B1_REJ{Rejection Candle?<br>Wick >= 0.85x body}
    B2 --> B2_REJ{Rejection Candle?<br>Wick >= 0.85x body}
    C --> C_TOUCH{Price touches<br>FVG zone?}

    B1_REJ -->|Yes| B1_ADX{ADX >= 22?}
    B1_REJ -->|No| SKIP1([Skip])
    B1_ADX -->|Yes| B1_FILTER[Hybrid Filter Check<br>Allowed all day in RTH]
    B1_ADX -->|No| SKIP2([Skip])

    B2_REJ -->|Yes| B2_FILTER[Hybrid Filter Check]
    B2_REJ -->|No| SKIP3([Skip])

    C_TOUCH -->|Yes| C_BOS{BOS enabled<br>for symbol?}
    C_TOUCH -->|No| SKIP4([Skip])
    C_BOS -->|ES/MES: OFF| SKIP5([Skip])
    C_BOS -->|NQ/MNQ: ON| C_LOSS{BOS losses<br>today < 1?}
    C_LOSS -->|Yes| C_FILTER[Hybrid Filter Check]
    C_LOSS -->|No| SKIP6([Skip])

    A_FILTER --> VALID
    B1_FILTER --> VALID
    B2_FILTER --> VALID
    C_FILTER --> VALID
```

## 3. Hybrid Filter Pipeline (V10.8)

```mermaid
flowchart TD
    ENTRY([Candidate Entry]) --> M1{MANDATORY 1<br>DI Direction}
    M1 -->|LONG: +DI > -DI| M2{MANDATORY 2<br>FVG Size >= 5 ticks}
    M1 -->|SHORT: -DI > +DI| M2
    M1 -->|Fail| REJECT([REJECT])

    M2 -->|Pass| OPT[OPTIONAL FILTERS<br>Need 2 of 3 to pass]
    M2 -->|Fail| REJECT

    OPT --> O1{Displacement<br>>= 1.0x avg body}
    OPT --> O2{ADX >= 11<br>or 3x disp + ADX >= 10}
    OPT --> O3{EMA Trend<br>EMA20 vs EMA50}

    O1 -->|Pass ✓| COUNT[Count Passes]
    O1 -->|Fail ✗| COUNT
    O2 -->|Pass ✓| COUNT
    O2 -->|Fail ✗| COUNT
    O3 -->|Pass ✓| COUNT
    O3 -->|Fail ✗| COUNT

    COUNT --> CHECK{Passes >= 2?}
    CHECK -->|Yes| TIME[Time Filters]
    CHECK -->|No| REJECT

    TIME --> T1{Midday Cutoff<br>12:00-14:00?}
    T1 -->|In range| REJECT
    T1 -->|Outside| T2{NQ/MNQ PM<br>After 14:00?}
    T2 -->|Yes + NQ| REJECT
    T2 -->|No| RISK{Min Risk Check<br>ES: 1.5 pts, NQ: 6 pts}
    RISK -->|Pass| ACCEPT([ACCEPT])
    RISK -->|Fail| REJECT
```

## 4. Entry Gate Checks

```mermaid
flowchart TD
    SIGNAL([Valid Entry Signal]) --> G1{Consecutive losses<br>< max? V10.13}
    G1 -->|No| BLOCK1([Blocked:<br>Consec Loss Stop])
    G1 -->|Yes| G2{Direction losses<br>< 3 today?}
    G2 -->|No| BLOCK2([Blocked:<br>Circuit Breaker])
    G2 -->|Yes| G3{BOS entry?}
    G3 -->|Yes| G4{BOS daily loss<br>limit reached?}
    G3 -->|No| G5
    G4 -->|Yes| BLOCK3([Blocked:<br>BOS Loss Limit])
    G4 -->|No| G5{Open trades<br>< 3?}
    G5 -->|No| BLOCK4([Blocked:<br>Max Open Trades])
    G5 -->|Yes| SIZING[Position Sizing]

    SIZING --> S1{How many trades<br>currently open?}
    S1 -->|0 open| CT3[3 Contracts<br>T1 + T2 + Runner]
    S1 -->|1+ open| CT2[2 Contracts<br>T1 + T2, no Runner]

    CT3 --> RETRACE{Retrace entry +<br>risk > 8 pts?<br>ES/MES only}
    CT2 --> RETRACE
    RETRACE -->|Yes| CT1[Force 1 Contract<br>V10.11 Risk Cap]
    RETRACE -->|No| ENTER([Open Trade])
    CT1 --> ENTER
```

## 5. Exit / Trade Management Flow

```mermaid
flowchart TD
    TRADE([Active Trade<br>Entry at FVG midpoint]) --> PHASE1{Price hits<br>Stop?}

    PHASE1 -->|Yes| FULL_STOP[FULL STOP<br>All contracts exit<br>at stop price]
    FULL_STOP --> LOSS([Loss recorded<br>Direction loss +1])

    PHASE1 -->|No| PHASE2{Price hits<br>3R target?}
    PHASE2 -->|No| PHASE1

    PHASE2 -->|Yes| T1_EXIT[T1 EXIT: 1 ct<br>Fixed profit at 3R<br>Trail stop → entry price]
    T1_EXIT --> PHASE3{Price hits<br>6R target?}

    PHASE3 -->|No| T1_TRAIL{T1 trail<br>stop hit?}
    T1_TRAIL -->|Yes| ALL_EXIT[ALL remaining exit<br>at trail stop<br>Breakeven floor]
    T1_TRAIL -->|No| PHASE3

    PHASE3 -->|Yes| ACTIVATE[Activate T2 + Runner trails<br>Floor at 3R profit]
    ACTIVATE --> T2_TRAIL{T2 trail<br>stop hit?<br>4-tick buffer}

    T2_TRAIL -->|No, keep trailing| T2_TRAIL
    T2_TRAIL -->|Yes| T2_CHECK{Has Runner?<br>3-ct trade only}

    T2_CHECK -->|No runner<br>2-ct trade| CLOSE_ALL[Close remaining<br>T2 profit locked]
    T2_CHECK -->|Yes| T2_EXIT[T2 EXIT: 1 ct<br>Runner continues]

    T2_EXIT --> RUNNER{Runner trail<br>stop hit?<br>6-tick buffer}
    RUNNER -->|No, keep trailing| RUNNER
    RUNNER -->|Yes| RUNNER_EXIT[RUNNER EXIT: 1 ct<br>at trail stop]
    RUNNER_EXIT --> DONE([Trade Complete])
    CLOSE_ALL --> DONE

    ALL_EXIT --> DONE
```

## 6. Structure Trail Update Logic

```mermaid
flowchart TD
    BAR([New Bar]) --> SWING{Check bar at i-2<br>for swing point}

    SWING --> SH{Swing High?<br>lookback=2}
    SWING --> SL{Swing Low?<br>lookback=2}

    SL -->|LONG trade| SL_CHECK{Swing > last<br>tracked swing?}
    SL_CHECK -->|Yes| SL_UPDATE[Update trail stop<br>= swing - buffer]
    SL_CHECK -->|No| SKIP([Skip: not higher])

    SH -->|SHORT trade| SH_CHECK{Swing < last<br>tracked swing?}
    SH_CHECK -->|Yes| SH_UPDATE[Update trail stop<br>= swing + buffer]
    SH_CHECK -->|No| SKIP2([Skip: not lower])

    SL_UPDATE --> BUFFERS{Which trail?}
    SH_UPDATE --> BUFFERS

    BUFFERS -->|T1 trail<br>3R to 6R| B1[2-tick buffer]
    BUFFERS -->|T2 trail<br>after 6R| B2[4-tick buffer]
    BUFFERS -->|Runner trail<br>after 6R + T2 exit| B3[6-tick buffer]
```

## 7. Per-Symbol Configuration

```mermaid
flowchart LR
    subgraph ES/MES [ES / MES]
        ES_BOS[BOS: OFF]
        ES_RISK[Min Risk: 1.5 pts]
        ES_BOS_CAP[Max BOS Risk: 8 pts]
        ES_RETRACE[Retrace Cap: 8 pts → 1ct]
        ES_CONSEC[Consec Loss: 2 → stop]
        ES_PM[PM Cutoff: No]
    end

    subgraph NQ/MNQ [NQ / MNQ]
        NQ_BOS[BOS: ON, 1 loss/day]
        NQ_RISK[Min Risk: 6.0 pts]
        NQ_BOS_CAP[Max BOS Risk: 20 pts]
        NQ_RETRACE[Retrace Cap: None]
        NQ_CONSEC[Consec Loss: OFF]
        NQ_PM[PM Cutoff: After 14:00]
    end
```

## 8. Session Timeline

```mermaid
gantt
    title Trading Session Timeline (EST)
    dateFormat HH:mm
    axisFormat %H:%M

    section Pre-Market
    Overnight FVG Tracking     :04:00, 05:30

    section Pre-RTH
    All Entry Types Active     :04:00, 09:30

    section RTH Morning
    Full Trading (All Types)   :09:30, 12:00
    B1 Overnight Retrace (all RTH) :09:30, 16:00

    section Midday
    NO ENTRIES (Lunch Lull)    :crit, 12:00, 14:00

    section Afternoon
    ES Trading Resumes         :14:00, 16:00
    NQ/MNQ CUTOFF              :crit, 14:00, 16:00

    section EOD
    Close All Positions        :milestone, 16:00, 0min
```

## 9. Position Sizing Decision

```mermaid
flowchart TD
    ENTRY([New Entry Signal]) --> OPEN{How many trades<br>currently open?}

    OPEN -->|0 trades| BASE[Base: 3 Contracts]
    OPEN -->|1+ trades| REDUCED[Reduced: 2 Contracts]

    BASE --> RETRACE1{Retrace entry?<br>Risk > max_retrace_risk?}
    REDUCED --> RETRACE2{Retrace entry?<br>Risk > max_retrace_risk?}

    RETRACE1 -->|ES/MES + risk > 8pts| FORCE1A[Force: 1 Contract]
    RETRACE1 -->|No| SPLIT3[Split: 1 T1 + 1 T2 + 1 Runner]

    RETRACE2 -->|ES/MES + risk > 8pts| FORCE1B[Force: 1 Contract]
    RETRACE2 -->|No| SPLIT2[Split: 1 T1 + 1 T2 + 0 Runner]

    SPLIT3 --> MAX[Max Exposure: 6 cts<br>3 open trades x 2 avg]
    SPLIT2 --> MAX
    FORCE1A --> MAX
    FORCE1B --> MAX
```
