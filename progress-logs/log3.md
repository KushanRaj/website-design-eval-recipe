# Progress Log #3

**Tuesday, 19 May - 2:48 AM**

Last log for the day before I go to sleep. Decent progress.

## Where things are landing

We had a bunch of different metrics:

- screenshot-based metrics
- HTML-based metrics
- a couple of others

We have come up with a bunch of different things, and right now the way it is looking is that we have sort of narrowed down what we want to do.

For screenshots, we are probably going to use DreamSim as a perceptual loss. We finally had a good, stable point where we can use VLMs as a judge. We also have decent confidence in the ability to rely on detecting elements, finding their match, and then computing a score from that.

## Hierarchical scoring

As alluded to in log two, there is also a hierarchical way to think about scoring.

If DreamSim and the VLM judge are not confident enough, then maybe we do not even bother going into pixel matching or more particular scores, because the broad signal already says this is clearly not good enough.

As models get better, and as those broad scores get stronger, then we can go deeper into the more specific rewards:

- pixel matching
- visual block scoring
- CSSOM
- things like that

The exact recipe will take a bit more experimentation, but this feels like the right shape.

## Runtime cleanup

The main goal now is to bring this under one umbrella so that it runs fine.

Right now it is really slow because we are making too many Playwright connections, opening pages repeatedly, and running the same kind of CDP call again and again. That is causing a lot of overhead.

I know this is a bit of an optimization that I should probably do later, but I am going to let the agent try to do it overnight as I sleep.

We have a benchmark where, if it messes up anywhere, then we know that it is doing something wrong with the scores. I do realize I could do this later, but might as well get it done right now.

## Generator side

The second side of the coin is the generator.

I have come up with a small agentic workflow which takes an input like: how many websites do you want, and do you have any direction on the types of datasets that you want?

It then generates that many. Obviously, I am going to experiment and ask it to make two or three first.

It has been built right now, but I have not tested it properly.

## Diagnostics

The good news is that in the process of discovering metrics, we also ended up discovering some diagnostic metrics which say things like:

- Does the page load?
- Does the page have any overflow?
- Is there any blocking element?

Just some good hygiene can also be maintained.

The bot code here is going to use a VLM as a judge, just to say how true it is to the concept we want.

## Concepts and schemas

The core idea here is that of concepts.

The main orchestrator generates concepts, and then these concepts are built and converted into schemas, like:

- what should pages look like
- what should happen in every page
- what should the dynamics be
- how should stuff like that be

That becomes the thing the generator is trying to build toward.

## Moving from raw HTML to DOM

As a goal of the pipeline cleanup, we also want to move from raw HTML to DOM.

There are two reasons:

- When it is static HTML, like what we are generating right now, the DOM and the HTML are basically going to be the same.
- The second we start adding JS, animations, React, or other frameworks, this DOM-based approach will work much better.

So the browser-rendered DOM is the abstraction that probably lasts longer.

## Manifest and validation

Right now, running sites and getting screenshots is trivial.

One thing I forgot to mention is that, as the website is generated, at the end there will also be a manifest generator. It says: these are the important points of the website. This is something you have to hover around and show the dropdown. This is what the design of the dropdown looks like. Stuff like that.

That way, we can take more appropriate screenshots.

During validation time, the verifier tries to regenerate the same manifest. If it can, then that passes. If it cannot, then there is some signal there too.

We use this to go to those particular spots and take screenshots. We had already alluded to this earlier.
