# Get it working

Before you can test your ideas, replicate the finding or get the code running once. 

Don’t try to optimise the code or do hundreds of runs. Log areas where you got stuck or where things look like they could be improved. These will be fodder for what you test next.

If you get stuck for >30 mins, rather than spending hours debugging, ask for help from your facilitator or others in the BlueDot community.

Other helpful tips:
- Use AI tools to speed up your work, like Claude Code or Cline.
- Get compute for your project from providers like RunPod or Hyperbolic.
- Access open source models via OpenRouter.
- Use fine-tuning API like TogetherAI or OpenAI.
- Leverage existing libraries, like Inspect, ControlArena, safety-tooling, TransformerLens

# Figure out what needs to be true

You've picked a direction. Now ask: what needs to be true for this to work?

## Exercises

### Generate assumptions

Write down as many assumptions as you can — aim for at least five. These might be about:

- The existing work: Is the original finding robust? Are there known issues with the codebase I'm building on? Have others tried extending this and hit a wall?
- The data: Is it available? Is it good enough quality? Is there enough of it? Does it actually measure what I think it measures?
- The method: Has anyone tried this approach before? What happened? Does it work at the scale I can afford to run it at? Am I sure this method tests what I think it's testing?
- The tools and resources: Can I run this with the compute and time I have? Do the libraries I need actually support what I'm trying to do? How long will each run take?
- The impact: If I got the result I'm hoping for, who would care? Would it change how someone builds or evaluates an AI system?

Answer:
- The existing work: I don't know if the findings are robust. I doubt it though. Issues with the codebase are the token limitations.
- The data: Quality of the data depends on the eval itself. I don't think that eval 
- The method: I'm not sure that this style of simple Evals can accurately measure instrumental convergence. Though it might work for the simple models that we're dealing with
- The tools and resources: I'm a bit afraid that the judging will be expensive in the end.
- The impact: not clear what the result would be. I don't think it will change much. 


# Deciding what to test first

Not all assumptions are equally important. For each one, ask:

How much does it matter? If this is wrong, does it kill the direction or just require an adjustment?
How uncertain am I? If you're already confident it holds, testing it is low value.
Start with assumptions that are both high-stakes and uncertain — these are your cruxes. For each one, figure out the cheapest way to check: a 30-minute experiment, prompting an LLM, reading a paper, asking someone who'd know.

A common mistake is testing something easy rather than something important. Before you commit to a test, ask: if I got this result, would it actually change what I do next? If not, pick a different assumption.

As you gain confidence in a direction, your tests should become more substantial — more careful experimental designs, larger runs, building out more of the MVP. Think of it as a ladder:
- Quick checks (minutes): ask an LLM, read a blog post, skim a paper, talk to someone who'd know
- Cheap experiments (hours): run a small-scale version, prototype a feature, test on a subset of data
- Serious runs (days): full experiments with proper controls, building out the working tool, running on full datasets

## Predict before you test

Before running any test, write down what you expect to find and why. 

Afterwards, compare your prediction to what actually happened, and most importantly, figure out why your prediction was off. This is one of the most effective ways to improve your judgment over time. 

[Here's an example](https://turntrout.com/predictions-for-shard-theory-mechanistic-interpretability) of researchers who stated their predictions _before _running their experiments.

Note down your reasoning in your log — what you will choose to test first and why.

## Exercises

### Your first cheap test

- What will you be testing?
- What do you expect the results of this test to be? Why?
- What result would make you change course?

Answer:

