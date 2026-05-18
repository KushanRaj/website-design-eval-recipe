# Progress Log #2

**Monday, 18 May - 10:43 PM**

I forgot to make a new work log earlier, so there is a lot here.

## Screenshot coverage

One interesting problem that came up while doing the toy experiment was: how do you generate screenshot pairs, and what does that even mean?

When you generate the base website, there is one sub-problem of deciding what screenshots you want to take.

In the very simple case, if there are five pages, then you go to all five pages and take screenshots. That sounds trivial, but there are a lot of interesting things you can do here.

## The manifest idea

One idea we came up with was a screenshot manifest.

When the Oracle agent is designing the website, it also writes a manifest that says: these are the important things I want screenshots of.

For example:

- this dropdown opens into this view
- this hover state changes the color
- these are the pages I want captured
- these are the viewport sizes I care about

Then, when testing the generated website, you can take that manifest and have the evaluator try to generate a similar manifest from the candidate code.

It would say: go to this page, hover here, click this, capture this state.

For plain HTML pages, this is probably quite simple. For modern frameworks, we will have to think more carefully about how this scales from a verification point of view.

Another thing is that if we cannot generate a one-to-one mapping from the old manifest to the new manifest, that itself is a signal. It means the generated website may not have replicated everything.

I think this manifest idea is interesting, but I would mark it as a little out of scope for now because there are more important things to do first.

## Partial information

There is also the question of partial information.

From a user perspective, they might just give a partial screenshot, or they might not give as many screenshots as we are giving in the toy setup. So how do we mimic that?

One way to think about it is as a scale:

- base case: screenshots of every main page of the website
- richer case: dropdowns, hover states, scroll positions
- 100% case: all relevant states and viewport sizes

One website could produce multiple tasks with different levels of information.

While verifying, we also need to keep that amount of information in mind. If the hover color was never shown in the information given to the model, then we should not penalize the model for not matching that hover color.

That part is a little tricky, but I think it is doable. We just have to make sure that the manifest-to-screenshot generator is reliable.

## What the toy experiment showed

The second thing we did was look at a lot of related work.

We found a bunch of papers, downloaded the available repositories, and tried running the code to get a sense of the metrics that are already out there.

We also generated one toy website. I asked Codex to generate the base page, and then I asked Claude to reproduce it in two ways:

- one trying to be authentic and faithful
- another one not really trying to be faithful at all

What was interesting is that some metrics do not give the full picture.

CLIP might tell you that the good page is around 90% accurate, but then it also tells you that the bad page is around 70% accurate. When you look at the bad page, there is no way that page is actually anywhere close to 70% accurate.

It is just that CLIP is not able to pick up some of the differences that matter here.

At a pixel level there is a lot of difference, and that shows up to a certain degree in pixel match. Stuff like SSIM or MSE is not really enough by itself, but it can still be used as one signal.

## Metric takeaways

The block-level methods seem much stronger.

For example, element-wise block matching gives you a bunch of useful information:

- how many blocks matched
- how many did not match
- for the matched blocks, how well they matched
- whether the local visual details were close

When you combine those things, you get a really useful signal.

The good website gets a very high score, something like 0.97 on one signal and 0.80 on another. The really bad page gets close to zero, or at least under 0.05 on the stricter block-level score.

That is a good sign because it gives a hierarchy.

First, you can ask whether the broad structure is matching. If that reward is high, then you can bring in other metrics like pixel-wise difference and weight them more.

Even in the good Claude case, it is not a 100% match. There are lots of small differences. But at a broad, global level, it is quite close.

So I think there are levels to this:

- some metrics are good for broad structure
- some are good for local specifics
- some are good for text, color, or pixel-level details

The important thing is not to expect one metric to do everything.

Another thing is that some of these methods use models like CLIP, and I am not fully convinced yet that they are worth it. CLIP is not giving me confidence that it can distinguish across different kinds of webpage quality really well.

If deterministic methods are already doing pretty well, then maybe the model-based methods should be supporting signals rather than primary reward signals.

## HTML versus rendered DOM

A lot of the methods rely on raw HTML as input.

I think what we probably need to do is make them work from the browser DOM instead.

Just like the manifest says "go to this state," we should go to that state, extract the DOM, and feed that into the HTML-based methods.

That seems valuable because when we move to React, Solid, or other modern frameworks, raw source files are not the right object anymore. The rendered DOM is the thing that actually exists in the browser.

Broadly, I think we are converging on something strong for validation. I want to work on this a little bit more and make it more ironclad.

After that, we can move more toward the generation side: take a schema or a spec, generate a website, and then use these verification tools to feed back into the agent and say, this does not match the spec, try again.

One interesting thing is that a lot of these methods are not only score-based. They also reveal categories of failure.

For example, this section of the UI is matching poorly, or this text is not matching, or this block is missing.

You can compute a reward from that, but in the generation pipeline maybe these diagnostics can also be used to make the next generation better.

## LLM-as-a-judge

Finally, on LLM-as-a-judge, I am still not super sold.

For one page, the score moved around enough that it made me wonder what the actual grounding is. If it ranges from around 0.7 to 0.8, what does that really mean?

One alternative is to not treat it as a precise score. Maybe you put things into buckets, like a CGPA or percentile grid, and map the output to that. But even then, if something is on the border, the grid might fluctuate.

I am not super sold on this yet.

Another way to think about it is as a gate. For example, a weaker model might be useful for saying: this replication is clearly weak, and this one is clearly good.

A stronger model might try to provide more of a gradient, and that is where the confusion comes in a bit more.

So maybe the LLM judge is better as a binary classifier inside a hierarchical setup, rather than as the core reward.

These are the things I have been thinking about, and this is what the experiments have revealed so far.
