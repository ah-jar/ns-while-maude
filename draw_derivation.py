#!/usr/bin/env python3
"""Ejecuta Maude, convierte los términos de prueba en árboles LaTeX y crea un PDF.
Soporta WHILE extendido (incluyendo repeat-until).
Soporta Semántica Natural (NS), Semántica de Paso Corto (SOS) y modo Comparativa (--compare).
Abrevia sentencias largas con S_i y árboles con \mathcal{T}_i.
Limpia automáticamente los archivos auxiliares (.tex, .aux, .log)."""

import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Node:
    rule: str
    statement: str
    before: str
    after: str
    children: tuple = ()
    next_stat: str = None  # Configuración intermedia < S', sigma' > en SOS
    semantics: str = "ns"  # 'ns' o 'sos'


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

    # --- CIERRE TRANSITIVO (SOS Secuencial) ---
    if constructor == "seqsos" and len(args) >= 1:
        children = tuple(parse_tree(arg) for arg in args if arg != "nilSOS")
        return Node("seq", "", "", "", children, semantics="sos")

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
    
    # Reglas de Repeat en NS:
    if constructor == "repeatffns" and len(args) == 5:
        # repeatffns(repeat S until C, M, T_S, T_RepeatRest, M'')
        return Node("repeat-ff", args[0], args[1], args[4], (parse_tree(args[2]), parse_tree(args[3])), semantics="ns")
    if constructor == "repeatttns" and len(args) == 4:
        # repeatttns(repeat S until C, M, T_S, M')
        return Node("repeat-tt", args[0], args[1], args[3], (parse_tree(args[2]),), semantics="ns")

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
    if constructor == "repeatsos" and len(args) == 4:
        # repeatsos(repeat S until C, M, S ; if C then skip else (repeat S until C), M)
        return Node("repeat", args[0], args[1], args[3], next_stat=args[2], semantics="sos")

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

    for word in ("skip", "if", "then", "else", "while", "do", "repeat", "until", "true", "false"):
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
        self.statement_map = {}
        self.statement_values = {}
        self.subtrees = []
        self.max_stat_length = 40

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
        
        if len(clean_text) > self.max_stat_length:
            if clean_text not in self.statement_map:
                i = len(self.statement_map) + 1
                name = rf"S_{{{i}}}"
                self.statement_map[clean_text] = name
                self.statement_values[name] = statement_latex(clean_text)
            return self.statement_map[clean_text]
            
        return statement_latex(clean_text)

    def format_state_value(self, text: str) -> str:
        if text == "empty":
            return r"\varnothing"
        
        bindings = re.findall(r"\[\s*'?([^\s:=|]+)\s*(?::=|\|->)\s*(-?\d+)\s*\]", text)
        remainder = re.sub(r"\[\s*'?([^\s:=|]+)\s*(?::=|\|->)\s*(-?\d+)\s*\]", "", text).strip()
        
        if bindings and not remainder:
            items = [rf"{identifier_latex(name)} \mapsto {value}" for name, value in bindings]
            return r"\{" + r",\; ".join(items) + r"\}"
        
        safe = text.replace("_", r"\_").replace("%", r"\%").replace("#", r"\#")
        return rf"\mathtt{{{safe}}}"


def get_transition(node: Node, ctx: Context) -> str:
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
    if node.rule == "seq":
        for child in node.children:
            split_tree(child, ctx)
        return 0

    child_derivs = []
    for child in node.children:
        if not child.children:
            child_derivs.append(format_axiom(child, ctx))
        else:
            child_id = split_tree(child, ctx)
            child_derivs.append(rf"\mathcal{{T}}_{{{child_id}}}")

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

    if not program.startswith("<"):
        program_term = f"< {program} , empty >"
    else:
        program_term = program

    if semantics_module == "SOS-WHILE-PROOFS":
        command = f"rew in {semantics_module} : run({program_term}) .\nquit\n"
    else:
        command = f"rew in {semantics_module} : {program_term} .\nquit\n"
        
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


def build_semantics_section(tree: Node, title: str) -> str:
    ctx = Context()
    split_tree(tree, ctx)

    derivations_tex = "\n\\vspace{0.2cm}\n".join(
        rf"\[ \mathcal{{T}}_{{{my_id}}} = {tex} \]"
        for my_id, tex in ctx.subtrees
    )
    
    statements_tex = "\n".join(
        rf"{name} &= {value} \\"
        for name, value in ctx.statement_values.items()
    )
    if statements_tex:
        statements_tex = (
            rf"\subsubsection*{{Sentencias Abreviadas}}" + "\n" +
            rf"\begin{{align*}}" + "\n" + statements_tex + "\n" + rf"\end{{align*}}"
        )

    states_tex = "\n".join(
        rf"{name} &= {value} \\"
        for name, value in ctx.sigma_values.items()
    )
    if states_tex:
        states_tex = (
            rf"\subsubsection*{{Estados}}" + "\n" +
            rf"\begin{{align*}}" + "\n" + states_tex + "\n" + rf"\end{{align*}}"
        )

    return rf"""\section*{{{title}}}
{{\small
{derivations_tex}
}}

{statements_tex}

{states_tex}
"""


def generate_single_latex(tree: Node, semantics_name: str) -> str:
    title = "Semántica Natural (NS)" if semantics_name == "ns" else "Semántica Operacional Estructurada (SOS)"
    section_body = build_semantics_section(tree, title)

    return rf"""\documentclass[a4paper]{{article}}
\usepackage[margin=1.5cm]{{geometry}}
\usepackage{{amsmath}}
\usepackage{{amssymb}}
\usepackage{{graphicx}}
\pagestyle{{empty}}
\begin{{document}}

{section_body}

\end{{document}}
"""


def generate_comparison_latex(tree_ns: Node, tree_sos: Node) -> str:
    section_ns = build_semantics_section(tree_ns, "1. Semántica Natural (NS - Big-Step)")
    section_sos = build_semantics_section(tree_sos, "2. Semántica Operacional Estructurada (SOS - Small-Step)")

    return rf"""\documentclass[a4paper]{{article}}
\usepackage[margin=1.5cm]{{geometry}}
\usepackage{{amsmath}}
\usepackage{{amssymb}}
\usepackage{{graphicx}}
\pagestyle{{empty}}
\begin{{document}}

\title{{\textbf{{Comparativa de Semánticas Formales (WHILE Enriquecido)}}}}
\date{{\vspace{{-1cm}}}}
\maketitle

{section_ns}

\newpage

{section_sos}

\end{{document}}
"""


def compile_pdf_in_temp(latex_code: str, output_pdf_path: Path) -> None:
    pdflatex = shutil.which("pdflatex")
    if not pdflatex:
        raise RuntimeError("No se encuentra 'pdflatex' en el PATH. Instala TeX Live en tu sistema.")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        tex_file = tmp_path / "derivation.tex"
        tex_file.write_text(latex_code, encoding="utf-8")

        process = subprocess.run(
            [pdflatex, "-interaction=nonstopmode", "-halt-on-error", tex_file.name],
            cwd=tmp_path,
            text=True,
            capture_output=True,
        )
        if process.returncode != 0:
            raise RuntimeError("Error al compilar LaTeX:\n\n" + process.stdout)

        generated_pdf = tmp_path / "derivation.pdf"
        shutil.copy(generated_pdf, output_pdf_path)


def main() -> None:
    args = sys.argv[1:]
    
    mode = "ns"
    if "--compare" in args or "--both" in args:
        mode = "compare"
        if "--compare" in args: args.remove("--compare")
        if "--both" in args: args.remove("--both")
    elif "--sos" in args:
        mode = "sos"
        args.remove("--sos")
    elif "--ns" in args:
        args.remove("--ns")
        
    program_file = Path(args[0] if len(args) > 0 else "program.while").resolve()
    output_pdf = Path(args[1] if len(args) > 1 else "derivation.pdf").resolve()

    main_file = Path("main.maude").resolve()
    if not main_file.exists():
        main_file = (Path(__file__).parent / "main.maude").resolve()

    if not main_file.exists():
        raise FileNotFoundError("No se encontró el archivo 'main.maude' en el directorio actual ni junto al script.")

    if mode == "compare":
        print("Modo Comparativa activado: Evaluando en NS y SOS...")
        term_ns = run_maude(program_file, main_file, "NS-WHILE-PROOFS")
        term_sos = run_maude(program_file, main_file, "SOS-WHILE-PROOFS")
        
        print("Parseando árboles de derivación...")
        tree_ns = parse_tree(term_ns)
        tree_sos = parse_tree(term_sos)
        
        print("Generando LaTeX comparativo y compilando...")
        latex_code = generate_comparison_latex(tree_ns, tree_sos)
    else:
        semantics_module = "SOS-WHILE-PROOFS" if mode == "sos" else "NS-WHILE-PROOFS"
        print(f"Evaluando programa bajo el módulo: {semantics_module}...")
        term = run_maude(program_file, main_file, semantics_module)
        
        print("Parseando el árbol de derivación...")
        tree = parse_tree(term)
        
        print("Generando LaTeX y compilando...")
        latex_code = generate_single_latex(tree, mode)

    compile_pdf_in_temp(latex_code, output_pdf)
    print(f"¡Éxito! PDF generado: {output_pdf}")


if __name__ == "__main__":
    main()