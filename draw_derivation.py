#!/usr/bin/env python3
"""Ejecuta Maude, convierte el término de prueba en un árbol LaTeX y crea un PDF.
Soporta Semántica Natural (NS) y Semántica de Paso Corto (SOS).
Abrevia sentencias largas con letras griegas (Gamma) para evitar desbordes."""

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Node:
    rule: str
    statement: str
    before: str
    after: str
    children: tuple = ()
    next_stat: str = None  # Utilizado para configuraciones intermedias < S', sigma' > en SOS
    semantics: str = "ns"  # Puede ser 'ns' o 'sos'


def split_arguments(text: str) -> list[str]:
    """Separa los argumentos de f(a,b,...) ignorando comas anidadas."""
    parts, start, depth = [], 0, 0
    for i, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
    parts.append(text[start:].strip())
    return parts


def parse_tree(term: str) -> Node:
    term = re.sub(r"\s+", " ", term).strip()
    match = re.fullmatch(r"([A-Za-z0-9_-]+)\((.*)\)", term)
    if not match:
        raise ValueError(f"Término de árbol no reconocido:\n{term}")

    constructor = match.group(1)
    args = split_arguments(match.group(2))

    # --- REGLAS DE SEMÁNTICA NATURAL (NS) ---
    if constructor == "assns" and len(args) == 3:
        return Node("ass", args[0], args[1], args[2], semantics="ns")
    if constructor == "skipns" and len(args) == 3:
        return Node("skip", args[0], args[1], args[2], semantics="ns")
    if constructor == "compns" and len(args) == 5:
        return Node("comp", args[0], args[1], args[4], (parse_tree(args[2]), parse_tree(args[3])), semantics="ns")
    if constructor == "ifttns" and len(args) == 4:
        return Node("if-tt", args[0], args[1], args[3], (parse_tree(args[2]),), semantics="ns")
    if constructor == "ifffns" and len(args) == 4:
        return Node("if-ff", args[0], args[1], args[3], (parse_tree(args[2]),), semantics="ns")
    if constructor == "whilettns" and len(args) == 5:
        return Node("while-tt", args[0], args[1], args[4], (parse_tree(args[2]), parse_tree(args[3])), semantics="ns")
    if constructor == "whileffns" and len(args) == 3:
        return Node("while-ff", args[0], args[1], args[2], semantics="ns")

    # --- REGLAS DE SEMÁNTICA DE PASO CORTO (SOS) ---
    if constructor == "asssos" and len(args) == 3:
        return Node("ass", args[0], args[1], args[2], semantics="sos")
    if constructor == "skipsos" and len(args) == 3:
        return Node("skip", args[0], args[1], args[2], semantics="sos")
    if constructor == "comp1sos" and len(args) == 5:
        return Node("comp^1", args[0], args[1], args[4], (parse_tree(args[2]),), next_stat=args[3], semantics="sos")
    if constructor == "comp2sos" and len(args) == 5:
        return Node("comp^2", args[0], args[1], args[4], (parse_tree(args[2]),), next_stat=args[3], semantics="sos")
    if constructor == "ifttsos" and len(args) == 4:
        return Node("if-tt", args[0], args[1], args[3], next_stat=args[2], semantics="sos")
    if constructor == "ifffsos" and len(args) == 4:
        return Node("if-ff", args[0], args[1], args[3], next_stat=args[2], semantics="sos")
    if constructor == "whilesos" and len(args) == 4:
        return Node("while", args[0], args[1], args[3], next_stat=args[2], semantics="sos")

    raise ValueError(f"Constructor no soportado: {constructor}/{len(args)}")


def identifier_latex(name: str) -> str:
    name = name.lstrip("'").replace("_", r"\_")
    return rf"\mathit{{{name}}}"


def statement_latex(text: str) -> str:
    variables: list[str] = []

    def save_variable(match: re.Match) -> str:
        variables.append(identifier_latex(match.group(1)))
        return f"@@V{len(variables) - 1}@@"

    text = re.sub(r"\s+", " ", text.strip())
    text = re.sub(r"'([A-Za-z0-9_-]+)", save_variable, text)

    replacements = [
        ("<=?", r"\leq"), ("=?", "="), ("&&?", r"\land"),
        ("!", r"\neg"), ("++", "+"), ("**", r"\cdot"),
        ("--", "-"), (":=", r"\mathrel{:=}"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)

    for word in ("skip", "if", "then", "else", "while", "do", "true", "false"):
        text = re.sub(rf"\b{word}\b", rf"\\mathbf{{{word}}}", text)

    for i, variable in enumerate(variables):
        text = text.replace(f"@@V{i}@@", variable)

    text = text.replace(" ", r"\;")
    return text


class Context:
    """Maneja el registro de estados, sentencias largas y subárboles durante el recorrido."""
    def __init__(self):
        self.sigma_map = {}
        self.sigma_values = {}
        self.gamma_map = {}
        self.gamma_values = {}
        self.subtrees = []
        self.max_stat_length = 40  # Límite de caracteres antes de abreviar la sentencia

    def get_sigma(self, text: str) -> str:
        key = re.sub(r"[\s'\(\)]+", "", text)
        if key not in self.sigma_map:
            i = len(self.sigma_map)
            name = rf"\sigma_{{{i}}}"
            self.sigma_map[key] = name
            clean_text = re.sub(r"\s+", " ", text.strip())
            self.sigma_values[name] = self.format_state_value(clean_text)
        return self.sigma_map[key]

    def get_statement(self, text: str) -> str:
        clean_text = re.sub(r"\s+", " ", text.strip())

        # Si la sentencia es muy larga, la abreviamos con \Gamma
        if len(clean_text) > self.max_stat_length:
            if clean_text not in self.gamma_map:
                i = len(self.gamma_map) + 1
                name = rf"\Gamma_{{{i}}}"
                self.gamma_map[clean_text] = name
                self.gamma_values[name] = statement_latex(clean_text)
            return self.gamma_map[clean_text]

        # Si es corta, la formateamos directamente
        return statement_latex(clean_text)

    def format_state_value(self, text: str) -> str:
        if text == "empty":
            return r"\varnothing"
        bindings = re.findall(r"\[\s*'([^\s:]+)\s*:=\s*(-?\d+)\s*\]", text)
        remainder = re.sub(r"\[\s*'([^\s:]+)\s*:=\s*(-?\d+)\s*\]", "", text).strip()
        if bindings and not remainder:
            items = [rf"{identifier_latex(name)} \mapsto {value}" for name, value in bindings]
            return r"\{" + r",\; ".join(items) + r"\}"
        safe = text.replace("_", r"\_").replace("%", r"\%").replace("#", r"\#")
        return rf"\mathtt{{{safe}}}"


def get_transition(node: Node, ctx: Context) -> str:
    """Genera la transición según sea NS o SOS utilizando sentencias abreviadas si es necesario."""
    stmt = ctx.get_statement(node.statement)
    left = rf"\left\langle {stmt},\; {ctx.get_sigma(node.before)}\right\rangle"
    arrow = r"\longrightarrow" if node.semantics == "ns" else r"\Rightarrow"

    if node.semantics == "sos" and node.next_stat:
        next_stmt = ctx.get_statement(node.next_stat)
        right = rf"\left\langle {next_stmt},\; {ctx.get_sigma(node.after)}\right\rangle"
    else:
        right = ctx.get_sigma(node.after)

    return rf"{left} {arrow} {right}"


def format_axiom(node: Node, ctx: Context) -> str:
    judgement = get_transition(node, ctx)
    sem_label = "ns" if node.semantics == "ns" else "sos"
    label = rf"\;\mathrm{{[{node.rule}_{{{sem_label}}}]}}"
    return rf"{judgement}{label}"


def format_rule(node: Node, child_derivs: list[str], ctx: Context) -> str:
    judgement = get_transition(node, ctx)
    sem_label = "ns" if node.semantics == "ns" else "sos"
    label = rf"\;\mathrm{{[{node.rule}_{{{sem_label}}}]}}"
    premises = r"\qquad".join(child_derivs)
    return rf"\frac{{{premises}}}{{{judgement}}}{label}"


def split_tree(node: Node, ctx: Context) -> int:
    child_derivs = []
    for child in node.children:
        if not child.children:
            child_derivs.append(format_axiom(child, ctx))
        else:
            child_id = split_tree(child, ctx)
            child_derivs.append(rf"\mathcal{{D}}_{{{child_id}}}")

    my_id = len(ctx.subtrees) + 1
    if not node.children:
        ctx.subtrees.append((my_id, format_axiom(node, ctx)))
    else:
        ctx.subtrees.append((my_id, format_rule(node, child_derivs, ctx)))
    return my_id


def extract_result(output: str) -> str:
    match = re.search(r"result\s+[^:]+:\s*", output)
    if not match:
        raise RuntimeError("Maude no devolvió un resultado.\n\n" + output)
    result = output[match.end():]
    result = re.split(r"\n(?:Bye\.|Maude>)", result, maxsplit=1)[0]
    return result.strip()


def run_maude(program_file: Path, main_file: Path, semantics_module: str) -> str:
    maude = shutil.which("maude")
    if not maude:
        raise RuntimeError("No se encuentra el ejecutable 'maude' en PATH.")

    program = program_file.read_text(encoding="utf-8").strip()
    if program.endswith("."):
        program = program[:-1].rstrip()

    command = f"rew in {semantics_module} : {program} .\nquit\n"
    process = subprocess.run(
        [maude, "-no-banner", main_file.name],
        input=command,
        text=True,
        capture_output=True,
        cwd=main_file.parent,
    )
    output = process.stdout + process.stderr
    if process.returncode != 0:
        raise RuntimeError(output)
    return extract_result(output)


def write_latex(tree: Node, tex_file: Path) -> None:
    ctx = Context()
    split_tree(tree, ctx)

    derivations_tex = "\n\n".join(
        rf"\[ \mathcal{{D}}_{{{my_id}}} = {tex} \]"
        for my_id, tex in ctx.subtrees
    )

    # Bloque de Sentencias Abreviadas (si existe alguna)
    gammas_tex = "\n".join(
        rf"{name} &= {value} \\"
        for name, value in ctx.gamma_values.items()
    )
    if gammas_tex:
        gammas_tex = rf"\section*{{Sentencias}}" + "\n" + rf"\begin{{align*}}" + "\n" + gammas_tex + "\n" + rf"\end{{align*}}"

    # Bloque de Estados
    states_tex = "\n".join(
        rf"{name} &= {value} \\"
        for name, value in ctx.sigma_values.items()
    )
    if states_tex:
        states_tex = rf"\begin{{align*}}" + "\n" + states_tex + "\n" + rf"\end{{align*}}"

    document = rf"""\documentclass[a4paper]{{article}}
\usepackage[margin=1.5cm]{{geometry}}
\usepackage{{amsmath}}
\usepackage{{amssymb}}
\usepackage{{graphicx}}
\pagestyle{{empty}}
\begin{{document}}

\section*{{Derivaciones}}
{derivations_tex}

{gammas_tex}

\section*{{Estados}}
{states_tex}

\end{{document}}
"""
    tex_file.write_text(document, encoding="utf-8")


def compile_pdf(tex_file: Path) -> Path:
    process = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_file.name],
        cwd=tex_file.parent,
        text=True,
        capture_output=True,
    )
    if process.returncode != 0:
        raise RuntimeError("Error al compilar LaTeX:\n\n" + process.stdout)
    return tex_file.with_suffix(".pdf")


def main() -> None:
    args = sys.argv[1:]

    semantics_module = "NS-WHILE-PROOFS"
    if "--sos" in args:
        semantics_module = "SOS-WHILE-PROOFS"
        args.remove("--sos")
    elif "--ns" in args:
        args.remove("--ns")

    program_file = Path(args[0] if len(args) > 0 else "program.while").resolve()
    main_file = Path(args[1] if len(args) > 1 else "main.maude").resolve()
    tex_file = Path(args[2] if len(args) > 2 else "derivation.tex").resolve()

    print(f"Evaluando programa bajo el módulo: {semantics_module}...")
    term = run_maude(program_file, main_file, semantics_module)

    print("Parseando el árbol de derivación...")
    tree = parse_tree(term)

    print("Escribiendo LaTeX y compilando...")
    write_latex(tree, tex_file)
    pdf_file = compile_pdf(tex_file)

    print(f"¡Éxito! PDF generado: {pdf_file}")


if __name__ == "__main__":
    main()
