---
# Machine-read by the autograder. Keep the keys; fill in the values.
name: "Roshan Kujur"
median_basis: "observations"        # the median your below_median rule computes: "observations" or "daily_close"
levels_attempted: [1, 2]    # e.g. [1, 2, 3, 4, 5]
llm_provider: "openai"        # e.g. "openai", "anthropic", "gemini"
llm_model: "gpt-4o-mini"
ai_tools_used: [Claude, ChatGPT]       # e.g. ["Claude Code", "Cursor", "ChatGPT"]
hours_spent: 9
---

# Decision log

Keep this to one page. Bullet points are fine. We read this before we read your code.

## Stage 1 — the false alerts

<!-- What caused them, and how did you establish it? -->
Well one thing has been cleard in the instructions, that the decision logic used to decide the alert sending has some computational error so that  was rectified as told.

But for the'Maple Store and Co' I found that that just sending the price simply being displayed in the homepage is not What will be the best way for the system for which it is intended to do!

There are differnt variants for some  products with diff prices and its not so usual but expect that the price can drop for even just one of the variant, so its better to keep record of all the products but moreover one level deeper to actaully keep in the records of all the variants of all the products and then have a check on that with regular price changes that which price gets dropped and then make the provision for sending the alarms based on that and also the parsing needs improvement.

So also chnaged the normlaiser a bit to prevent the price parsing issues with currency Euro.
<!-- same changes in the watcher and normaliser code so the new price are not always checked against the 'none'  and the the euro prices are conveted to cents correctly-->

## Stage 2 — the median

<!-- How is the median computed, and why? What did you decide about edge cases? -->

My Startegies are - 

Median strategy: Observation-based rolling median using all valid prices within the trailing 30-day window (excluding current observation).

Threshold: Will Alert when current price ≤ median × (1 − pct/100); minimum 3 prior valid observations required.

Edge cases: Ignored null prices and out-of-window observations; detected currency changes and add notes; handled multiple observations per day; normalize timestamps to UTC.

Alert priority: below_median overrides drop_pct; maximum one alert per product per evaluation.
Modularity: Implemented median logic separately in rule_below_median() for easier extension.

Testing: Added tests for median calculation, minimum observations, null handling, window filtering, and rule priority.

Limitations - 
Maple extractor test fails due to a mismatch between the returned list and expected Observation object.

Watcher regression test fails due to a discrepancy between the expected (25%) and actual (20%) drop calculation.

## Levels 3–5 — how you got in

<!-- Per level: what the store does, how your agent handles it, what you chose not to do (and why). -->

## Stage 3 — what the model got wrong

<!-- Failure patterns you saw. Which labels you think are wrong and how you decided. What you'd change with another day. -->

<!-- The LLM-Extractor Module  -->
The LLM-Extractor extracts observations from unknown stores so for that tried to enhance html preprocessing 
The System Prompt should be more clear providing every details regarding what work you want the agent to  do so added more instructions point wise like handling discounts, packs size,etc
Also added validation to check for price , currency format and availabilty values, etc.

Restructured the evaluation pipeline to benchmark LLM extraction across 90 labelled HTML snapshots. Implemented response caching, error tracking, performance metrics, and baseline comparison. Also developed a separate diagnostic script to identify price-extraction errors by comparing predicted values against ground-truth labels.

Limitations-
For some of the test smaples wrong currencies were generated 

While checking for the output observation being recieved for bz-045 sample 
LLM extraction also failed sometimes conveying -  ProviderError: Connection error. after 2 retries but gave the correct output on the again running the check.

The initial LLM evaluation across 90 snapshots achieved 60% exact price accuracy (54/90), with Nordkart performing better at 82.22% (37/45) compared to Bazaario at 37.78% (17/45). This highlighted limitations in price extraction, particularly for Bazaario, indicating a need to improve price selection and formatting interpretation.

If I another day - I would have definitely inspected the snapshots and labels to understand about why the error in price extraction is coming with possible imporvements to be reflected in the System Prompt to strengthen more the System Prompts or anything more that can be improved.

## Where AI helped and where it didn't

<!-- Be specific. "The assistant wrote the retry logic correctly first time, but confidently misread a response header and I lost 40 minutes before checking the raw response" is the level of detail we want. -->

The AI helped me in providing code in structured form for the decisions that I made regarding the strategies to try to build the robust system like properly parsing the observations for variants of the products of Maple and Co, So design and implementation choices are mine but AI provided code for it.

## If I had another day

Would work more on this system understanding it more, solving for the limitations and meeting up for every requirement of the assessement.

Would definitely try on adding intelligence coming from the LLMs would try if the can create agentic setup for extractions for different stores and atleast try to build agentic workflow till raising alerts right starting from parsing 

