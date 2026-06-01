"""
============================================================
  DSL Compiler – Main Driver
  Orchestrates all 4 phases of the compiler pipeline:
    1. Lexical Analysis   (Lexer)
    2. Syntax Analysis    (Parser → AST)
    3. Semantic Analysis  + Intermediate Code Generation (ICG)
    4. Target Code Generation (CodeGen → Assembly)
  Produces: listing file, token table, TAC, Assembly output
============================================================
"""

import sys
import os
import argparse

# Add src to path when running directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lexer    import Lexer,    print_token_table
from parser   import Parser
from icg      import ICG
from codegen  import CodeGen
from listing  import ListingGenerator
from ast_nodes import ASTPrinter
from ai_dsl import detect_ai_dsl, transpile_ai_dsl, AIDSLCompileError
from agent_orchestrator import build_agent_report


BANNER = """
╔══════════════════════════════════════════════════════════╗
║          DSL / Pascal-like Language Compiler             ║
║          Full 4-Phase Compiler Pipeline                  ║
║          Lexer → Parser → ICG → CodeGen                  ║
╚══════════════════════════════════════════════════════════╝
"""


def compile_source(source: str,
                   verbose: bool = True,
                   output_dir: str = ".",
                   program_name: str = "program") -> dict:
    """
    Full compilation pipeline.
    Returns dict with all phase results for integration / testing.
    """
    results = {
        'tokens':    [],
        'lex_errors': [],
        'ast':       None,
        'parse_errors': [],
        'tac':       [],
        'sem_errors': [],
        'asm':       [],
        'listing':   '',
        'success':   False,
    }

    listing = ListingGenerator(source)

    # ══════════════════════════════════════════════════════
    #  PHASE 1 – LEXICAL ANALYSIS
    # ══════════════════════════════════════════════════════
    if verbose:
        print("\n" + "─" * 60)
        print("  PHASE 1 – LEXICAL ANALYSIS")
        print("─" * 60)

    lexer          = Lexer(source)
    tokens, lex_err = lexer.tokenize()
    results['tokens']     = tokens
    results['lex_errors'] = lex_err

    listing.add_all_lex_errors(lex_err)

    if verbose:
        print_token_table(tokens)
        if lex_err:
            print(f"\n  ✗ {len(lex_err)} Lexical error(s):")
            for e in lex_err:
                print(f"    {e}")
        else:
            print(f"\n  ✓ Lexical analysis completed. {len(tokens)} tokens produced.")

    # ══════════════════════════════════════════════════════
    #  PHASE 2 – SYNTAX ANALYSIS (PARSER)
    # ══════════════════════════════════════════════════════
    if verbose:
        print("\n" + "─" * 60)
        print("  PHASE 2 – SYNTAX ANALYSIS (PARSER)")
        print("─" * 60)

    # Filter out ERROR tokens before parsing
    clean_tokens = [t for t in tokens if t.type.name != 'ERROR']
    parser       = Parser(clean_tokens)
    ast          = parser.parse()
    parse_err    = parser.errors
    results['ast']          = ast
    results['parse_errors'] = parse_err

    listing.add_all_parse_errors(parse_err)

    if verbose:
        if parse_err:
            print(f"\n  ✗ {len(parse_err)} Parse error(s):")
            for e in parse_err:
                print(f"    {e}")
        else:
            print(f"\n  ✓ Parsing successful. AST built.")
        if ast and verbose:
            print("\n  AST:")
            printer = ASTPrinter()
            printer.print(ast)

    # ══════════════════════════════════════════════════════
    #  PHASE 3 – INTERMEDIATE CODE GENERATION (+ Semantics)
    # ══════════════════════════════════════════════════════
    if verbose:
        print("\n" + "─" * 60)
        print("  PHASE 3 – INTERMEDIATE CODE GENERATION")
        print("─" * 60)

    if ast is None:
        if verbose:
            print("  ✗ Skipping ICG — no AST available (parser failed).")
        listing_text = listing.generate(
            output_path=os.path.join(output_dir, f"{program_name}.lst"))
        results['listing'] = listing_text
        return results

    icg       = ICG()
    tac       = icg.generate(ast)
    sem_err   = icg.errors + icg.sym_tab.errors
    results['tac']        = tac
    results['sem_errors'] = sem_err

    listing.add_all_sem_errors(sem_err)

    if verbose:
        icg.print_tac()
        icg.sym_tab.dump()
        if sem_err:
            print(f"\n  ✗ {len(sem_err)} Semantic error(s):")
            for e in sem_err:
                print(f"    {e}")
        else:
            print(f"\n  ✓ ICG successful. {len(tac)} TAC instructions generated.")

    # ══════════════════════════════════════════════════════
    #  PHASE 4 – TARGET CODE GENERATION
    # ══════════════════════════════════════════════════════
    all_errors = lex_err + parse_err + sem_err

    if verbose:
        print("\n" + "─" * 60)
        print("  PHASE 4 – TARGET CODE GENERATION")
        print("─" * 60)

    if all_errors:
        if verbose:
            print(f"  ✗ Code generation SKIPPED — {len(all_errors)} error(s) present.")
            print("    (Per spec: target code only generated if no errors)")
    else:
        cg  = CodeGen(tac)
        asm = cg.generate()
        results['asm'] = asm
        results['success'] = True

        asm_path = os.path.join(output_dir, f"{program_name}.asm")
        with open(asm_path, 'w', encoding='utf-8') as f:
            f.write(cg.get_asm_string())

        if verbose:
            cg.print_asm()
            print(f"\n  ✓ Assembly written to: {asm_path}")

    # ══════════════════════════════════════════════════════
    #  LISTING FILE
    # ══════════════════════════════════════════════════════
    lst_path     = os.path.join(output_dir, f"{program_name}.lst")
    listing_text = listing.generate(output_path=lst_path)
    results['listing'] = listing_text

    if verbose:
        print("\n" + "═" * 60)
        print("  LISTING FILE")
        print("═" * 60)
        print(listing_text)
        print(f"\n  Listing written to: {lst_path}")

    return results




def build_failed_compile_results(source: str, error: Exception) -> dict:
    """Create a compiler-shaped result for early failures so the agent can still report."""
    line = getattr(error, 'line', None)
    col = getattr(error, 'col', getattr(error, 'column', None))
    message = getattr(error, 'message', str(error))
    return {
        'success': False,
        'tokens': [],
        'lex_errors': [],
        'parse_errors': [error],
        'sem_errors': [],
        'ast': None,
        'tac': [],
        'asm': [],
        'listing': f'Early compiler failure: {message}',
        'source_language': 'ai_workflow_dsl' if detect_ai_dsl(source) else 'pascal_like_core_dsl',
        'translated_source': '',
        'original_source': source,
        'runtime_warnings': [],
        'error_line': line,
        'error_column': col,
    }

def compile_any_source(source: str,
                       verbose: bool = True,
                       output_dir: str = ".",
                       program_name: str = "program",
                       with_agent: bool = False,
                       agent_backend: str = "deterministic",
                       llm_provider: str = None,
                       llm_model: str = None) -> dict:
    """Compile either the legacy Pascal-like DSL or the AI workflow DSL.

    The agent is optional and runs after compilation. It never mutates compiler
    inputs, AST, TAC, or generated assembly.
    """
    if detect_ai_dsl(source):
        transpiled = transpile_ai_dsl(source)
        results = compile_source(
            transpiled.translated_source,
            verbose=verbose,
            output_dir=output_dir,
            program_name=program_name,
        )
        results['source_language'] = transpiled.source_language
        results['translated_source'] = transpiled.translated_source
        results['original_source'] = source
    else:
        results = compile_source(source, verbose=verbose, output_dir=output_dir, program_name=program_name)
        results['source_language'] = 'pascal_like_core_dsl'
        results['translated_source'] = source
        results['original_source'] = source

    if with_agent:
        agent_report = build_agent_report(
            source,
            results,
            backend=agent_backend,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
        results['agent_report'] = agent_report.to_dict()
        results['agent_report_text'] = agent_report.to_text()
    return results


# ──────────────────────────────────────────────────────────
#  CLI entry point
# ──────────────────────────────────────────────────────────
def main():
    print(BANNER)

    ap = argparse.ArgumentParser(
        description='DSL Pascal-like Compiler – Full 4-Phase Pipeline')
    ap.add_argument('source_file', help='Path to source file (.pas or .aidl)')
    ap.add_argument('-o', '--output-dir', default='.', help='Output directory')
    ap.add_argument('-q', '--quiet', action='store_true', help='Suppress verbose output')
    ap.add_argument('--agent-report', action='store_true', help='Run the AI agent debugger after compilation')
    ap.add_argument('--agent-backend', default='deterministic', choices=['deterministic', 'llm', 'langgraph', 'langgraph-llm', 'auto'], help='Agent execution mode')
    ap.add_argument('--llm-provider', default=None, help='Optional LLM provider: openai or gemini')
    ap.add_argument('--llm-model', default=None, help='Optional model name for the selected LLM provider')
    args = ap.parse_args()

    if not os.path.exists(args.source_file):
        print(f"ERROR: Source file not found: {args.source_file}")
        sys.exit(1)

    with open(args.source_file, 'r', encoding='utf-8') as f:
        source = f.read()

    prog_name = os.path.splitext(os.path.basename(args.source_file))[0]
    os.makedirs(args.output_dir, exist_ok=True)

    try:
        results = compile_any_source(
            source,
            verbose=not args.quiet,
            output_dir=args.output_dir,
            program_name=prog_name,
            with_agent=args.agent_report,
            agent_backend=args.agent_backend,
            llm_provider=args.llm_provider,
            llm_model=args.llm_model,
        )
    except Exception as exc:
        results = build_failed_compile_results(source, exc)
        if args.agent_report:
            agent_report = build_agent_report(
                source,
                results,
                runtime_result={'output': '', 'warnings': []},
                runtime_error={'message': str(exc), 'line': getattr(exc, 'line', None), 'column': getattr(exc, 'col', None)},
                backend=args.agent_backend,
                llm_provider=args.llm_provider,
                llm_model=args.llm_model,
            )
            results['agent_report'] = agent_report.to_dict()
            results['agent_report_text'] = agent_report.to_text()

    if args.agent_report:
        print("\n" + "═" * 60)
        print("  AI AGENT DEBUGGER REPORT")
        print("═" * 60)
        print(results.get('agent_report_text', 'Agent report unavailable.'))

    total_errors = len(results['lex_errors']) + \
                   len(results['parse_errors']) + \
                   len(results['sem_errors'])

    print(f"\n{'✓ COMPILATION SUCCEEDED' if results['success'] else '✗ COMPILATION FAILED'}")
    sys.exit(0 if results['success'] else 1)



if __name__ == '__main__':
    main()
