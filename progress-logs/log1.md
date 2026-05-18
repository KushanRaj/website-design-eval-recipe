# Progress Log #1

**Monday, 18 May - 3:46 PM**

I've spent some time looking into Harbor. Got a gist of it in terms of what structure and configs it expects.

I've been thinking about the problem a little bit. My understanding initially was that it was going to be more like: how do you source websites, or how do you interact with websites to get a good sense of whether they have been replicated correctly?

It now feels more like there are two axes:

1. **Sample generation**: how do you get a wide variety of different websites to experiment and test against, and how do you make this scalable? Can you go from some website spec that has a number of pages, per-page descriptions, and maybe just a small amount of wiring across the different web pages of the site?
2. **Evaluation**: since this is a particular design, we probably need to understand things like sleek, modern, dense, verbose, cluttered, and so on.

The problem also breaks down across the kind of output we ask for:

1. Simple HTML/CSS applications
2. React or animations, basically more modern applications

## The end goal

The way to think about this is that the end product is something like a user saying: "Here is the screenshot. Make it look like this." How do you do that?

That is the end goal. Sample generation is one aspect of it, but I don't think it is the most important thing initially. The easiest version would be to not focus so much on the full recipe yet, but to just have some set of samples generated, even a few short samples.

## The more important task: how do you validate?

Given a screenshot, how do you evaluate whether the output is good?

Right now I think the interesting thing is that you may not even need pure screenshots. You can maybe evaluate output HTML against ground-truth HTML, but what is the problem there?

You're obviously introducing a certain kind of bias. You're saying that the way the model structures its code, or the way it makes things functional, has to be close to the way the Oracle wrote the HTML. That introduces a certain level of boundedness, assuming the Oracle itself is also not perfect.

Given that there are so many ways to achieve the same thing, especially in design, HTML-to-HTML comparison need not be the most important thing. We do not care that much about functionality here. We care more about how things look.

From a functionality standpoint, it would be important to understand how the HTML is written. But the flip side is that, if we are writing pure HTML and CSS, it becomes pretty obvious whether the given HTML corresponds to the given screenshot. You're limiting yourself in that capacity to say that this will only work with HTML, which I think is pretty ancient in that sense.

## What can the grader output?

I think we'll have to do experiments to figure this out. There is no one short answer here.

One way is to define what the expected output is that we want to validate on, and what goes into the input. We do have the original HTML, but I don't think we should look at the HTML directly.

We should look at how you get stuff out of the rendered page. For example: how do you say that buttons are of this size and this ratio, especially with respect to the viewport and their position? How do you get a list of "this was my original HTML and this is the layout"? Like, this button exists, there are 100 buttons here, and they are of this size.

The next thing is that the CSS tells you all of that: the CSSOM.

Should I even use an LLM as a judge? Is there a deterministic loop that we can make? I don't think there is a right answer yet. There is a lot that we need to figure out, and I think that is where the focus should be.

## First experiments

I think we can start off with some very simple pages and experiment with what good evaluation functions are. Then we can build from there.

How to package it, and how to scale it out, can come later.

The first set of experiments should be: what is the good output artifact? For example, do I want to evaluate at the HTML level, or at the CSSOM level? Stuff like that is important to understand.

I luckily have a benchmarking browser page. It's a bunch of JavaScript, a website that I have locally which I can run. I also have WebArena and stuff which I could use just to get things off the bat. I think we can think of things along those lines.

## Evaluation tooling and agentic outputs

I also came across RewardKit. Not that RewardKit in itself gave any major insight, but the tooling around it is interesting. It already has similarity checks, so the trivial case can be checked quickly. It also points toward evaluating agent traces and other agentic outputs.

The broader takeaway is not specifically that RewardKit is the answer. It is more that there is useful tooling here, but the core question is still: how do you cleanly evaluate?

I have two thoughts. One is that the tooling is a bit secondary. The core is still the HTML evaluation, or whatever screenshot evaluation we decide is useful.

The reason it is secondary is because right now we will not necessarily have an agentic setup for the first couple of tests. We just want to make sure we understand what good evaluation functions are. That is the first thing.

Once we have more clarity on what is a good signal and what is a bad signal, we can bring in tooling like RewardKit, agentic judges, and trace evaluation. That becomes more relevant when we are evaluating not just the final screenshot or HTML, but the agent's process and outputs as a whole.

Some of the evaluation tests we want to run are around whether a scan or an LLM can even qualitatively, or reliably, give a reproducible score across the same two screenshots. Stuff like that would be interesting. But I do think this tooling comes a little bit later.
