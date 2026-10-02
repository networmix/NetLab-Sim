"""Deliver an inbox entry to an agent's current generation, stamped the way
scheduled runtime deliveries are."""

from dataclasses import replace


def deliver_now(sim, device, agent, entry):
    generation = sim.agents.generation(device, agent)
    if generation is not None and entry.generation is None:
        entry = replace(entry, generation=generation)
    return sim.agents.deliver(device, agent, entry)


def stamped(sim, device, agent, entry):
    """``entry`` stamped with the agent's current generation."""
    return replace(entry, generation=sim.agents.generation(device, agent))
