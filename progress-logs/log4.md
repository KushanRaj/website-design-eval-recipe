# Progress Log #4

**Wednesday, 20 May - around 3 or 4 AM**

I did not make a log the entire day today, so I am doing it at night. Today has been a lot of progress.

There were a couple of interesting insights, a couple of silly mistakes, and a couple of logistical problems. But overall, the day moved things forward quite a bit.

## Generator pipeline

The main positive is that the generator recipe pipeline is now pretty solid and malleable. It can generate a good variety of websites.

Each site or page-ish run takes around ten minutes on average, but the nice thing is that this is parallel by nature. In ten minutes you could have one page, or you could have one hundred pages, depending on API rate limits and how much parallelism we want to use.

The verification loop is useful, though it adds a lot of time and cost. The kinds of websites we are getting are of good quality. There were also cases where the builder and verification loop got stuck because logging was not good enough, and we fixed that.

There are no obvious diversity issues initially, though there is a bit of a bias toward education websites. That is probably not surprising given the examples and prompts so far, but it is worth keeping in mind.

## Animation

I also dabbled with animations.

Getting good-quality websites with animations is harder in an automated pipeline, especially if the specifications are vague. The takeaway is that the schema needs to be very specific about what the animation should look like and should also help the verifier see the animation happen.

For now, I would treat animation reward as a separate add-on story, not the main website reward story. Animation generation is starting to exist, and the capture path is starting to exist, but I do not want to mix that into the main static website reward yet.

We are starting simple with things like color changes and motion. With the metrics we have defined, I think we can eventually track these specific aspects, but that should come after the main reward loop is more stable.

## Unified metrics and reward curriculum

As mentioned last night before signing off, we now have a unified pipeline that combines the research metrics and gives us a way to run them together.

It is not necessarily better, faster, or cleaner code yet, but it is functional.

We also spent a lot of time developing the reward curriculum. My strong opinion is that if a model is failing the earlier tasks, we should not even bother giving it reward for a higher task.

For example, the basics are:

- did all the required screenshots get generated?
- were the expected states captured?
- is there a decent amount of element or block matching?

If that much is not happening, there is no point in putting too much weight on pixel match. Pixel match can become a confounding factor unless the websites are already roughly similar.

The way I think about it is like school assessments. Each assessment has a particular weight, but if you do not pass the basic ones, you should not really qualify for the final assessment.

## What the current reward is showing

The good news is that I asked Claude to generate a medium-quality reproduction for one of the websites generated yesterday, and the reward metric shows a gradient nicely.

Very faithful websites score above `0.9`. Medium-quality reproductions sit around `0.6` to `0.7`. Terrible ones are around `0.1`.

That is a good sign. The quality comes from how we defined the curriculum.

The basic curriculum has a small weight, but it includes things like screenshot coverage and the ability to match snapshots. More advanced metrics include:

- number of matching elements
- VLM confidence in the match
- bounding-box overlap
- text content inside the boxes
- more local visual and layout comparisons

When I say some basic metrics vary a lot, I do not mean they are randomly fluctuating between runs. I mean they are sensitive across quality levels. Higher-quality websites score very high, lower-quality websites score very low, whereas something like DreamSim feels more compressed. DreamSim is useful as a broad perceptual signal, but it may not express the finer differences as sharply.

Pixel match should probably only be used once the websites are already roughly similar, because getting a perfect pixel match requires perfect colors, spacing, font sizes, and layout. That is useful, but only at the right stage of the curriculum.

## Screenshot manifests and replay

Snapshot matching continues to be an important part of the story.

The base case is capturing all the main pages in a site. But the more interesting case is when hovering over an element triggers a popup, a dropdown, a color change, or some other visual state. We need to capture those states too.

Generating and replaying this was not trivial because browsers are messy, and Playwright can be a bit wacky to use.

We had to instruct the agent not to use generic `div` selectors, but to use stamped elements or actual attributes that refer to the thing being interacted with. The replay aspect should get an element and replay the action so that we capture the intended visual state.

One important clarification: when I say that if a replay action fails we can discard it, I mean during oracle capture.

If an optional dropdown or hover state cannot be reliably captured while building the oracle manifest, then it should be pruned from the canonical manifest. If it is not in the oracle manifest, we should not penalize the candidate for missing it.

But if the oracle manifest does include that state, then failing to recreate it on the generated website should count as a useful failure signal.

That distinction matters because the oracle manifest defines what is fair to score.

## Model behavior

A key insight is that if I ask a GPT-based model to replicate a webpage made by another GPT model, it does a really good job, even when the smaller model is GPT-5.4 mini.

That says something about model biases. Claude's placements and designs are slightly different, while GPT-5.4 mini replicated the GPT-made page in one shot.

We have not seen catastrophic issues where the model completely disobeys actions. For simple websites, the agents replicate around eighty percent of the design, which aligns with the scores we see.

The differences are mostly in:

- font placement
- font sizes
- relative positioning
- colors
- spacing

I have noticed Claude has its own color preferences. If you show it beige, it interprets that in its own way. But it is still premature to draw conclusions.

## Rendered DOM as the stable object

For moving to React, Solid, or other frameworks, the important decision from day one is that whenever we interact with the browser, inspect code, or understand HTML, we should not depend on raw generated files.

We should look at what the browser shows us.

Ultimately, whether the site is written in TypeScript, React, Solid, or plain HTML, the browser renders it into a DOM. That is the most stable point of view.

So the evaluator should be able to translate fairly naturally to React or Solid. The more interesting issues will probably be:

- how do you start the server?
- how do you serve the app?
- how do you make sure the browser reaches the same state?

But conceptually, browser-rendered DOM is the right abstraction.

## Harbor setup

Setting up Harbor was fairly straightforward, but we wanted to be a little optimal because we are running local models and a vision-transformer-based screenshot signal for some tasks.

We could probably do without the vision-transformer piece, but since it is set up, we might as well use it.

The screenshot-based model signal is useful as a broad perceptual output. The VLM is also useful, though I would still be careful about treating it as a deterministic precise score.

We also created Docker images to address the Claude Code initialization issue, where installing Claude Code during test time can fail on systems with less than 4 GB of memory. The Docker image now comes with Claude Code preloaded, so it loads during test time instead of trying to install from scratch.

## Where this leaves things

The broad shape feels much clearer now.

The generator can produce websites. The verifier can validate them. The manifest gives us a procedural way to capture important states. The evaluator can run multiple metrics over browser-rendered artifacts. The reward curriculum gives us a way to combine those metrics without pretending that every score should matter equally from the beginning.

There is still cleanup to do, and we still need more controlled experiments before locking in the exact reward recipe. But the system now feels much more real than it did a day ago.
