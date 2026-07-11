"""
PDDL Parser for the Trucks Domain.

Parses domain.pddl and problem .pddl files into structured Python objects
for use by the simulator and replanner.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Tuple, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PddlAction:
    """Represents a PDDL action definition from the domain file."""
    name: str
    parameters: List[Tuple[str, str]]  # (param_name, type)
    precondition_raw: str
    effect_raw: str


@dataclass
class PddlDomain:
    """Parsed PDDL domain."""
    name: str
    requirements: List[str]
    types: Dict[str, str]            # type -> parent type
    predicates: List[str]            # raw predicate strings
    actions: List[PddlAction]


@dataclass
class GoalCondition:
    """A single goal predicate, e.g. (delivered package1 l3 t3)."""
    predicate: str
    arguments: List[str]


@dataclass
class PddlProblem:
    """Parsed PDDL problem file."""
    name: str
    domain: str
    objects: Dict[str, List[str]]    # type -> list of object names
    init_facts: List[Tuple[str, List[str]]]  # (predicate, [args])
    goal_conditions: List[GoalCondition]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_balanced_parens(text: str, start: int) -> str:
    """Extract the substring from an opening '(' to its matching ')'."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]


def _parse_facts(text: str) -> List[Tuple[str, List[str]]]:
    """Parse a list of ground facts like (at truck1 l3) from an init block."""
    facts = []
    for m in re.finditer(r'\((\w[\w-]*)\s+([\w\s]+?)\)', text):
        pred = m.group(1)
        args = m.group(2).split()
        facts.append((pred, args))
    return facts


# ---------------------------------------------------------------------------
# Domain parser
# ---------------------------------------------------------------------------

def parse_domain(filepath: str) -> PddlDomain:
    """Parse a PDDL domain file and return a PddlDomain object."""
    text = Path(filepath).read_text(encoding='utf-8')

    # Domain name
    name_match = re.search(r'\(domain\s+([\w-]+)\)', text)
    domain_name = name_match.group(1) if name_match else "unknown"

    # Requirements
    req_match = re.search(r':requirements\s+((?::[\w-]+\s*)+)', text)
    requirements = re.findall(r':([\w-]+)', req_match.group(1)) if req_match else []

    # Types
    types = {}
    types_match = re.search(r'\(:types\s+(.*?)\)', text, re.DOTALL)
    if types_match:
        type_text = types_match.group(1)
        # Parse "truckarea time location locatable - object\n truck package - locatable"
        for line in type_text.strip().split('\n'):
            line = line.strip()
            if ' - ' in line:
                parts = line.split(' - ')
                parent = parts[-1].strip()
                children = parts[0].split()
                for child in children:
                    child = child.strip()
                    if child:
                        types[child] = parent

    # Predicates (store raw for reference)
    predicates = []
    pred_match = re.search(r'\(:predicates\s+(.*?)\)\s*\n', text, re.DOTALL)
    if pred_match:
        pred_text = pred_match.group(1)
        predicates = re.findall(r'\([^()]+\)', pred_text)

    # Actions
    actions = []
    action_pattern = re.compile(r'\(:action\s+(\w+)', re.DOTALL)
    for m in action_pattern.finditer(text):
        action_name = m.group(1)
        action_block = _find_balanced_parens(text, m.start())

        # Parameters
        params = []
        param_match = re.search(r':parameters\s*\(([^)]*)\)', action_block)
        if param_match:
            param_text = param_match.group(1)
            # Parse "?p - package ?t - truck ?a1 - truckarea ?l - location"
            tokens = param_text.split()
            i = 0
            while i < len(tokens):
                if tokens[i].startswith('?'):
                    param_name = tokens[i]
                    param_type = ""
                    # Collect all param names before the dash
                    names = [param_name]
                    j = i + 1
                    while j < len(tokens) and tokens[j].startswith('?'):
                        names.append(tokens[j])
                        j += 1
                    if j < len(tokens) and tokens[j] == '-':
                        param_type = tokens[j + 1] if j + 1 < len(tokens) else ""
                        i = j + 2
                    else:
                        i = j
                    for n in names:
                        params.append((n, param_type))
                else:
                    i += 1

        # Precondition and effect (raw strings)
        prec_match = re.search(r':precondition\s+', action_block)
        prec_raw = ""
        if prec_match:
            prec_raw = _find_balanced_parens(action_block, prec_match.end())

        eff_match = re.search(r':effect\s+', action_block)
        eff_raw = ""
        if eff_match:
            eff_raw = _find_balanced_parens(action_block, eff_match.end())

        actions.append(PddlAction(
            name=action_name,
            parameters=params,
            precondition_raw=prec_raw,
            effect_raw=eff_raw,
        ))

    return PddlDomain(
        name=domain_name,
        requirements=requirements,
        types=types,
        predicates=predicates,
        actions=actions,
    )


# ---------------------------------------------------------------------------
# Problem parser
# ---------------------------------------------------------------------------

def parse_problem(filepath: str) -> PddlProblem:
    """Parse a PDDL problem file and return a PddlProblem object."""
    text = Path(filepath).read_text(encoding='utf-8')

    # Problem name
    name_match = re.search(r'\(problem\s+([\w-]+)\)', text)
    problem_name = name_match.group(1) if name_match else "unknown"

    # Domain reference
    domain_match = re.search(r'\(:domain\s+([\w-]+)\)', text)
    domain_name = domain_match.group(1) if domain_match else "unknown"

    # Objects: parse typed object declarations
    objects: Dict[str, List[str]] = {}
    obj_start = re.search(r'\(:objects', text)
    if obj_start:
        obj_block = _find_balanced_parens(text, obj_start.start())
        # Remove outer (:objects ... )
        obj_text = obj_block[len("(:objects"):-1]
        for line in obj_text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            if ' - ' in line:
                parts = line.split(' - ')
                obj_type = parts[-1].strip()
                obj_names = parts[0].split()
                if obj_type not in objects:
                    objects[obj_type] = []
                for name in obj_names:
                    name = name.strip()
                    if name:
                        objects[obj_type].append(name)

    # Init facts — use balanced parens to get the full (:init ...) block
    init_facts = []
    init_start = re.search(r'\(:init', text)
    if init_start:
        init_block = _find_balanced_parens(text, init_start.start())
        # Remove outer (:init ... )
        init_text = init_block[len("(:init"):-1]
        init_facts = _parse_facts(init_text)

    # Goal conditions — use balanced parens for (:goal ...) block
    goal_conditions = []
    goal_start = re.search(r'\(:goal', text)
    if goal_start:
        goal_block = _find_balanced_parens(text, goal_start.start())
        # Remove outer (:goal ... )
        goal_text = goal_block[len("(:goal"):-1]
        for m in re.finditer(r'\(([\w-]+)\s+([\w\s]+?)\)', goal_text):
            pred = m.group(1)
            args = m.group(2).split()
            goal_conditions.append(GoalCondition(predicate=pred, arguments=args))

    return PddlProblem(
        name=problem_name,
        domain=domain_name,
        objects=objects,
        init_facts=init_facts,
        goal_conditions=goal_conditions,
    )

