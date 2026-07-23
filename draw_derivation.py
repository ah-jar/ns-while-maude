#!/usr/bin/env python3
"""
Ejecuta Maude, convierte los términos de prueba en árboles LaTeX y crea un PDF.
Soporta WHILE extendido y soporta trazas masivas de ejecución incrementando el límite de recursión de Python.
"""

import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# --- ELEVAR LÍMITE DE RECURSIÓN PARA EJECUCIONES LARGAS ---
sys.setrecursionlimit(100000)


@dataclass
class Node:
    rule: str
    statement: str
    before: str
    after: str
    children: tuple = ()
    next_stat: str = None
    semantics: str = "ns"
    is_stuck: bool = False


def split_arguments(text: str) -> list[str]:
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


def parse_tree(term: str, semantics: str = "ns") -> Node:
    term = re.sub(r"\s+", " ", term).strip()

    match_run_stuck = re.fullmatch(r"run\(\s*\(?\s*<\s*(.*?)\s*,\s*(.*?)\s*>\s*\)?\s*\)", term)
    if match_run_stuck:
        return Node("stuck", match_run_stuck.group(1).strip(), match_run_stuck.group(2).strip(), "stuck", semantics=semantics, is_stuck=True)

    match = re.fullmatch(r"([A-Za-z0-9_-]+)\((.*)\)", term)
    if not match:
        raise ValueError(f"Término de árbol no reconocido:\n{term}")

    constructor = match.group(1)
    args = split_arguments(match.group(2))

    # --- FALLBACK PARA CASO RUN ATASCADO ---
    if constructor == "run":
        if len(args) == 1:
            inner = args[0].strip()
            if inner.startswith("(") and inner.endswith(")"):
                inner = inner[1:-1].strip()
            if inner.startswith("<") and inner.endswith(">"):
                parts = inner[1:-1].split(",", 1)
                if len(parts) == 2:
                    return Node("stuck", parts[0].strip(), parts[1].strip(), "stuck", semantics=semantics, is_stuck=True)
        elif len(args) == 2:
            s_part = args[0].strip()
            m_part = args[1].strip()
            if s_part.startswith("<") and m_part.endswith(">"):
                return Node("stuck", s_part[1:].strip(), m_part[:-1].strip(), "stuck", semantics=semantics, is_stuck=True)
        raise ValueError(f"Constructor 'run' atascado no pudo ser procesado. Argumentos: {args}")

    # --- CIERRE TRANSITIVO ---
    if constructor == "seqsos" and len(args) >= 1:
        children = tuple(parse_tree(arg, "sos") for arg in args if arg != "nilSOS")
        return Node("seq", "", "", "", children, semantics="sos")

    # --- REGLAS DE SEMÁNTICA NATURAL (NS) ---
    if constructor == "assns" and len(args) == 3:
        return Node("ass", args[0], args[1], args[2], semantics="ns")
    if constructor == "skipns" and len(args) == 3:
        return Node("skip", args[0], args[1], args[2], semantics="ns")
    if constructor == "compns" and len(args) == 5:
        return Node("comp", args[0], args[1], args[4], (parse_tree(args[2], "ns"), parse_tree(args[3], "ns")), semantics="ns")
    if constructor == "ifttns" and len(args) == 4:
        return Node("if-tt", args[0], args[1], args[3], (parse_tree(args[2], "ns"),), semantics="ns")
    if constructor == "ifffns" and len(args) == 4:
        return Node("if-ff", args[0], args[1], args[3], (parse_tree(args[2], "ns"),), semantics="ns")
    if constructor == "whilettns" and len(args) == 5:
        return Node("while-tt", args[0], args[1], args[4], (parse_tree(args[2], "ns"), parse_tree(args[3], "ns")), semantics="ns")
    if constructor == "whileffns" and len(args) == 3:
        return Node("while-ff", args[0], args[1], args[2], semantics="ns")
    if constructor == "whileabortns" and len(args) == 4:
        return Node("while-abort", args[0], args[1], args[3], (parse_tree(args[2], "ns"),), semantics="ns")
    if constructor == "repeatffns" and len(args) == 5:
        return Node("repeat-ff", args[0], args[1], args[4], (parse_tree(args[2], "ns"), parse_tree(args[3], "ns")), semantics="ns")
    if constructor == "repeatttns" and len(args) == 4:
        return Node("repeat-tt", args[0], args[1], args[3], (parse_tree(args[2], "ns"),), semantics="ns")
    if constructor == "repeatabortns" and len(args) == 4:
        return Node("repeat-abort", args[0], args[1], args[3], (parse_tree(args[2], "ns"),), semantics="ns")
    if constructor == "forttns" and len(args) == 6:
        return Node("for-tt", args[0], args[1], args[5], (parse_tree(args[2], "ns"), parse_tree(args[3], "ns"), parse_tree(args[4], "ns")), semantics="ns")
    if constructor == "forffns" and len(args) == 3:
        return Node("for-ff", args[0], args[1], args[2], semantics="ns")
    if constructor == "forabortns" and len(args) == 5:
        return Node("for-abort", args[0], args[1], args[4], (parse_tree(args[2], "ns"), parse_tree(args[3], "ns")), semantics="ns")
    if constructor == "abortns" and len(args) == 3:
        return Node("abort", args[0], args[1], args[2], semantics="ns")
    if constructor == "compabortns" and len(args) == 4:
        return Node("comp-abort", args[0], args[1], args[3], (parse_tree(args[2], "ns"),), semantics="ns")
    if constructor == "assertttns" and len(args) == 4:
        return Node("assert-tt", args[0], args[1], args[3], (parse_tree(args[2], "ns"),), semantics="ns")
    if constructor == "assertffns" and len(args) == 3:
        return Node("assert-ff", args[0], args[1], args[2], semantics="ns")

    # --- REGLAS DE SEMÁNTICA DE PASO CORTO (SOS) ---
    if constructor == "asssos" and len(args) == 3:
        return Node("ass", args[0], args[1], args[2], semantics="sos")
    if constructor == "skipsos" and len(args) == 3:
        return Node("skip", args[0], args[1], args[2], semantics="sos")
    if constructor == "comp1sos" and len(args) == 5:
        return Node("comp^1", args[0], args[1], args[4], (parse_tree(args[2], "sos"),), next_stat=args[3], semantics="sos")
    if constructor == "comp2sos" and len(args) == 5:
        return Node("comp^2", args[0], args[1], args[4], (parse_tree(args[2], "sos"),), next_stat=args[3], semantics="sos")
    if constructor == "ifttsos" and len(args) == 4:
        return Node("if-tt", args[0], args[1], args[3], next_stat=args[2], semantics="sos")
    if constructor == "ifffsos" and len(args) == 4:
        return Node("if-ff", args[0], args[1], args[3], next_stat=args[2], semantics="sos")
    if constructor == "whilesos" and len(args) == 4:
        return Node("while", args[0], args[1], args[3], next_stat=args[2], semantics="sos")
    if constructor == "repeatsos" and len(args) == 4:
        return Node("repeat", args[0], args[1], args[3], next_stat=args[2], semantics="sos")
    if constructor == "forsos" and len(args) == 4:
        return Node("for", args[0], args[1], args[3], next_stat=args[2], semantics="sos")
    if constructor == "abortsos" and len(args) == 3:
        return Node("abort", args[0], args[1], args[2], semantics="sos")
    if constructor == "compabortsos" and len(args) == 4:
        return Node("comp-abort", args[0], args[1], args[3], (parse_tree(args[2], "sos"),), semantics="sos")
    if constructor == "assertsos" and len(args) == 4:
        return Node("assert", args[0], args[1], args[3], next_stat=args[2], semantics="sos")

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

    for word in ("skip", "abort", "if", "then", "else", "while", "do", "repeat", "until", "for", "to", "assert", "before", "true", "false"):
        text = re.sub(rf"\b{word}\b", rf"\\mathbf{{{word}}}", text)

    for i, variable in enumerate(variables):
        text = text.replace(f"@@V{i}@@", variable)

    text = text.replace(" ", r"\;")
    return text


class Context:
    def __init__(self):
        self.sigma_keys = {}
        self.sigma_raw_texts = {}
        self.statement_map = {}
        self.statement_values = {}
        self.subtrees = []
        self.max_stat_length = 30
        self.tree_counter = 0

    def get_sigma(self, text: str) -> str:
        clean_text = re.sub(r"\s+", " ", text.strip())

        if clean_text == "stuck":
            return r"\mathbf{stuck}"

        if clean_text == "Bottom":
            return r"\bot"

        if clean_text == "empty":
            return r"\varnothing"

        norm_key = re.sub(r"[\s'\(\)]+", "", clean_text)

        if norm_key not in self.sigma_keys:
            sig_id = len(self.sigma_keys)
            self.sigma_keys[norm_key] = sig_id
            self.sigma_raw_texts[sig_id] = clean_text

        sig_id = self.sigma_keys[norm_key]
        return f"@@SIG_{sig_id}@@"

    def get_statement(self, text: str) -> str:
        clean_text = re.sub(r"\s+", " ", text.strip())
        length_check_text = clean_text.replace("'", "")

        if len(length_check_text) > self.max_stat_length:
            if clean_text not in self.statement_map:
                i = len(self.statement_map) + 1
                name = rf"S_{{{i}}}"
                self.statement_map[clean_text] = name
                self.statement_values[name] = statement_latex(clean_text)
            return self.statement_map[clean_text]

        return statement_latex(clean_text)

    def format_state_value(self, text: str) -> str:
        bindings = re.findall(r"'?([a-zA-Z0-9_-]+)\s*(?:\|->|:=)\s*(-?\d+)", text)
        if bindings:
            items = [rf"{identifier_latex(name)} \mapsto {value}" for name, value in bindings]
            return r"\{" + r",\; ".join(items) + r"\}"

        safe = text.replace("_", r"\_").replace("%", r"\%").replace("#", r"\#")
        return rf"\mathtt{{{safe}}}"


def get_transition(node: Node, ctx: Context) -> str:
    stmt = ctx.get_statement(node.statement)
    left = rf"\left\langle {stmt},\; {ctx.get_sigma(node.before)}\right\rangle"

    if node.is_stuck:
        arrow = r"\mathbin{\not\longrightarrow}" if node.semantics == "ns" else r"\mathbin{\not\Rightarrow}"
        right = r"\mathbf{stuck}"
    else:
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


def split_tree(node: Node, ctx: Context) -> str:
    if node.rule == "seq":
        for child in node.children:
            split_tree(child, ctx)
        return ""

    child_derivs = []

    for child in node.children:
        if child.children:
            child_id = split_tree(child, ctx)
            child_derivs.append(f"@@T_{child_id}@@")
        else:
            child_axiom = format_axiom(child, ctx)
            if len(child_axiom) > 160:
                child_id = split_tree(child, ctx)
                child_derivs.append(f"@@T_{child_id}@@")
            else:
                child_derivs.append(child_axiom)

    my_id = str(ctx.tree_counter)
    ctx.tree_counter += 1

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


def run_maude_command(command: str, main_file: Path) -> str:
    maude = shutil.which("maude")
    if not maude:
        raise RuntimeError("No se encuentra el ejecutable 'maude' en PATH.")

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


def get_program_term(program_file: Path) -> str:
    program = program_file.read_text(encoding="utf-8").strip()
    if program.endswith("."):
        program = program[:-1].rstrip()
    if not program.startswith("<"):
        return f"< {program} , empty >"
    return program


def run_sos(program_term: str, main_file: Path) -> Node:
    command = f"rew in SOS-WHILE-PROOFS : run({program_term}) .\nquit\n"
    term = run_maude_command(command, main_file)
    return parse_tree(term, semantics="sos")


def run_ns(program_term: str, main_file: Path) -> Node:
    command = f"rew in NS-WHILE-PROOFS : {program_term} .\nquit\n"
    term = run_maude_command(command, main_file)

    term = re.sub(r"\s+", " ", term).strip()
    if term.startswith("(") and term.endswith(")"):
        term = term[1:-1].strip()

    match_config = re.fullmatch(r"<\s*(.*?)\s*,\s*(.*?)\s*>", term)
    if match_config:
        return Node("stuck", match_config.group(1).strip(), match_config.group(2).strip(), "stuck", semantics="ns", is_stuck=True)

    return parse_tree(term, semantics="ns")


def get_init_and_final_sigma_ids(tree: Node, ctx: Context) -> tuple[int | None, int | None]:
    if tree.rule == "seq" and tree.children:
        init_text = tree.children[0].before
        final_text = tree.children[-1].after
    else:
        init_text = tree.before
        final_text = tree.after

    norm_init = re.sub(r"[\s'\(\)]+", "", re.sub(r"\s+", " ", init_text.strip()))
    norm_final = re.sub(r"[\s'\(\)]+", "", re.sub(r"\s+", " ", final_text.strip()))

    init_id = ctx.sigma_keys.get(norm_init)
    final_id = ctx.sigma_keys.get(norm_final)
    return init_id, final_id


def build_semantics_section(tree: Node, title: str) -> str:
    ctx = Context()

    main_steps = list(tree.children) if tree.rule == "seq" else [tree]
    n_steps = len(main_steps)

    main_step_info = []
    for idx, step_node in enumerate(main_steps):
        if n_steps == 1:
            label = r"\mathit{ini}"
        elif idx == 0:
            label = r"\mathit{ini}"
        elif idx == n_steps - 1:
            label = r"\mathit{fin}"
        else:
            label = str(idx)

        root_id = split_tree(step_node, ctx)
        if root_id:
            main_step_info.append((root_id, label))

    if not ctx.subtrees:
        return rf"\section*{{{title}}}"

    tree_display_map = {}
    subtree_step_map = {}
    tex_by_id = {uid: tex for uid, tex in ctx.subtrees}

    global_counter = 1
    for step_idx, (root_id, _) in enumerate(main_step_info):
        queue = [root_id]
        visited_in_step = set()
        while queue:
            curr = queue.pop(0)
            if curr in visited_in_step:
                continue
            visited_in_step.add(curr)
            subtree_step_map[curr] = step_idx

            if curr not in tree_display_map:
                tree_display_map[curr] = str(global_counter)
                global_counter += 1

            tex = tex_by_id.get(curr, "")
            child_ids = re.findall(r"@@T_(\d+)@@", tex)
            for cid in child_ids:
                if cid not in visited_in_step:
                    queue.append(cid)

    for uid, _ in ctx.subtrees:
        if uid not in tree_display_map:
            tree_display_map[uid] = str(global_counter)
            global_counter += 1

    init_sig_id, final_sig_id = get_init_and_final_sigma_ids(tree, ctx)
    sigma_display_map = {}

    if init_sig_id is not None:
        sigma_display_map[init_sig_id] = r"\sigma_{\mathit{ini}}"
    if final_sig_id is not None and final_sig_id != init_sig_id:
        sigma_display_map[final_sig_id] = r"\sigma_{\mathit{fin}}"

    current_sig_index = 1
    for sig_id in ctx.sigma_raw_texts:
        if sig_id not in sigma_display_map:
            sigma_display_map[sig_id] = rf"\sigma_{{{current_sig_index}}}"
            current_sig_index += 1

    derivations_tex_list = []
    current_step = None

    for uid, tex in ctx.subtrees:
        my_display = tree_display_map.get(uid, uid)
        step_of_uid = subtree_step_map.get(uid, None)

        if current_step is not None and step_of_uid is not None and step_of_uid != current_step:
            derivations_tex_list.append(r"\[ \Downarrow \]")

        if step_of_uid is not None:
            current_step = step_of_uid

        def replace_tree_placeholder(match):
            cid = match.group(1)
            return rf"\mathcal{{T}}_{{{tree_display_map.get(cid, cid)}}}"

        def replace_sigma_placeholder(match):
            sig_id = int(match.group(1))
            return sigma_display_map.get(sig_id, f"\\sigma_{{{sig_id}}}")

        final_tex = re.sub(r"@@T_(\d+)@@", replace_tree_placeholder, tex)
        final_tex = re.sub(r"@@SIG_(\d+)@@", replace_sigma_placeholder, final_tex)

        # ÁRBOLES: Ecuación LaTeX normal a tamaño real 100% (sin reescalados)
        derivations_tex_list.append(rf"\[ \mathcal{{T}}_{{{my_display}}} = {final_tex} \]")

    derivations_tex = "\n\\vspace{0.1cm}\n".join(derivations_tex_list)

    # SENTENCIAS: parbox para forzar salto de línea automático si el código impreso es largo
    stmt_rows = []
    for name, value in ctx.statement_values.items():
        stmt_rows.append(rf"{name} &= \parbox[t]{{0.85\linewidth}}{{$\raggedright {value}$}} \\")

    statements_tex = "\n".join(stmt_rows)
    if statements_tex:
        statements_tex = (
            rf"\subsubsection*{{Sentencias Abreviadas}}" + "\n" +
            rf"\begin{{align*}}" + "\n" + statements_tex + "\n" + rf"\end{{align*}}"
        )

    # ESTADOS: Uso de multicols (3 columnas verticales) que evita desbordar la memoria TeX
    state_items = []
    for sig_id, clean_text in ctx.sigma_raw_texts.items():
        lhs = sigma_display_map[sig_id]
        rhs = ctx.format_state_value(clean_text)
        state_items.append(rf"\noindent ${lhs} = {rhs}$ \par")

    states_tex = "\n".join(state_items)
    if states_tex:
        states_tex = (
            rf"\subsubsection*{{Estados}}" + "\n" +
            rf"\begin{{multicols}}{{3}}" + "\n" +
            states_tex + "\n" +
            rf"\end{{multicols}}"
        )

    return rf"""\section*{{{title}}}

{derivations_tex}

{statements_tex}

{states_tex}
"""


def generate_single_latex(tree: Node, semantics_name: str) -> str:
    title = "Semántica Natural (NS)" if semantics_name == "ns" else "Semántica Operacional Estructurada (SOS)"
    section_body = build_semantics_section(tree, title)

    return rf"""\documentclass[12pt,a4paper]{{article}}
\usepackage[margin=1.2cm, landscape]{{geometry}}
\usepackage{{amsmath}}
\usepackage{{amssymb}}
\usepackage{{graphicx}}
\usepackage{{multicol}}
\allowdisplaybreaks
\pagestyle{{empty}}
\begin{{document}}

{section_body}

\end{{document}}
"""


def generate_comparison_latex(tree_ns: Node, tree_sos: Node) -> str:
    section_ns = build_semantics_section(tree_ns, "1. Semántica Natural (NS - Big-Step)")
    section_sos = build_semantics_section(tree_sos, "2. Semántica Operacional Estructurada (SOS - Small-Step)")

    return rf"""\documentclass[12pt,a4paper]{{article}}
\usepackage[margin=1.2cm, landscape]{{geometry}}
\usepackage{{amsmath}}
\usepackage{{amssymb}}
\usepackage{{graphicx}}
\usepackage{{multicol}}
\allowdisplaybreaks
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

    program_term = get_program_term(program_file)

    if mode == "compare":
        print("Modo Comparativa activado: Evaluando en NS y SOS...")
        tree_ns = run_ns(program_term, main_file)
        tree_sos = run_sos(program_term, main_file)
        print("Generando LaTeX comparativo y compilando...")
        latex_code = generate_comparison_latex(tree_ns, tree_sos)
    else:
        semantics_module = "SOS-WHILE-PROOFS" if mode == "sos" else "NS-WHILE-PROOFS"
        print(f"Evaluando programa bajo el módulo: {semantics_module}...")

        if mode == "sos":
            tree = run_sos(program_term, main_file)
        else:
            tree = run_ns(program_term, main_file)

        print("Generando LaTeX y compilando...")
        latex_code = generate_single_latex(tree, mode)

    compile_pdf_in_temp(latex_code, output_pdf)
    print(f"¡Éxito! PDF generado delegando la ejecución a Maude: {output_pdf}")


if __name__ == "__main__":
    main()
