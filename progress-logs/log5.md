# Progress Log #5

**Wednesday, 20 May - 12:20 PM**

Good progress.

Everything is running, it is working through Harbor, and the pipeline is parallelizable. There are still a couple of issues being found and fixed, but the good news is that the reward curriculum is behaving the way I would want it to behave.

I will attach some screenshots separately, but the example I looked at was a sports-tracking website. It has players, matches, cards, and a few different page states.

At a broad visual level, the reproduction looks quite similar. This matches the intuition we have been building: current agents can replicate the overall impression of a website fairly well.

But when you look at the finer details, the problems start showing up.

The model either does not understand some of the visual features in the screenshots well enough, or it cannot consistently remember and generalize them across ten to twelve screenshots. So the broad layout is there, but the local details are weaker.

Examples include:

- the design of a player card
- relative positioning
- repeated layout structure
- details inside modals
- consistency across related screenshots

This is where the reward curriculum is useful.

The broad visual and VLM-based scores are not terrible. The VLM score is around `70%`, and many of the broad visual scores are around `70-80%`.

But the stricter methods tell a different story. The bounding-box methods and the HTML/layout-based methods give a much lower score, closer to `40%`, because the relative structures and positioning do not really add up.

Because of the curriculum, the final reward drops to around `0.48`.

I think that is appropriate.

This is more empirical than meticulous right now, but my preference is that this kind of reproduction should not get a high score. It looks similar from far away, but it misses too many finer details. Over time, those details are exactly what should matter if the goal is faithful website replication rather than just producing something in the same broad category.

## Issues found

One issue showed up with an HTML-based metric.

It failed because it expected the two screenshots to be the same size. This is an error we had not seen locally. The bigger problem is that the reward output still ended up showing a non-zero value in a way that could skew the final reward.

That should be fixed. If a metric fails because of a size mismatch or any other evaluator issue, it should be explicit in the output. It should either be zeroed in a controlled way or reported as a metric failure, but it should not silently distort the reward.

Another issue is runtime.

The current coding agent used synchronous APIs for Playwright calls, and the VLM API calls are also synchronous. That is annoying because the whole evaluation path is naturally parallel.

Right now, a task takes roughly 30 minutes end to end:

- around 15 minutes for the model to generate the site
- around 15-20 minutes for evaluation

I am now moving the relevant pieces toward asynchronous execution. This should give a large time improvement, especially because there are many independent screenshots, page states, and VLM calls.

## Current takeaway

The main takeaway is that the system is now running in a more realistic setup, and the reward curriculum is giving a useful signal.

It is not just saying "this looks broadly similar, so give it a high score." It is able to keep the broad visual similarity in mind while still penalizing missing structure, positioning, and local design details.

That feels like the right direction.
