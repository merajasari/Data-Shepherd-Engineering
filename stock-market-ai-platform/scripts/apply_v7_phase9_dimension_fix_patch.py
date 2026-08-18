"""Fix V7 Phase 9 duplicate-column handling for context interactions."""

from pathlib import Path

PHASE9 = Path("ml/v7/phase9.py")


def main():
    if not PHASE9.exists():
        raise FileNotFoundError(f"Missing generated Phase 9 module: {PHASE9}")

    text = PHASE9.read_text(encoding="utf-8")

    old = '''    for context_id, context_col in CONTEXT_SPECS.items():
        cols = base_cols + [context_col]
        g = daily[cols].replace([np.inf, -np.inf], np.nan).dropna().copy()
        if len(g) < 30:
            rows.append({
                "context_id": context_id,
                "context_column": context_col,
                "days": int(len(g)),
                "eligible": False,
            })
            continue

        z_context = _zscore(g[context_col])
        z_breadth = _zscore(g["breadth_5d_centered"])
        interaction = z_context * z_breadth

        fit = _ols(
            g["full_confounder_residual_ic"].to_numpy(float),
            np.column_stack([
                g["breadth_5d_centered"].to_numpy(float),
                g["spy_return_5d"].to_numpy(float),
                g["spy_return_20d_ctx"].to_numpy(float),
                z_context.to_numpy(float),
                interaction.to_numpy(float),
            ]),
            ["breadth", "spy5", "spy20", "context_z", "breadth_x_context_z"],
        )
        rows.append({
            "context_id": context_id,
            "context_column": context_col,
            "days": int(len(g)),
            "eligible": True,
            "coef_breadth": fit["coef_breadth"],
            "t_breadth": fit["t_breadth"],
            "coef_context_z": fit["coef_context_z"],
            "t_context_z": fit["t_context_z"],
            "coef_breadth_x_context_z": fit["coef_breadth_x_context_z"],
            "t_breadth_x_context_z": fit["t_breadth_x_context_z"],
            "r2": fit["r2"],
        })
'''

    new = '''    for context_id, context_col in CONTEXT_SPECS.items():
        # context_col may already be one of the baseline controls (notably
        # SPY_5D_RETURN). Preserve one physical column so pandas returns a
        # one-dimensional Series instead of a duplicate-column DataFrame.
        cols = list(dict.fromkeys(base_cols + [context_col]))
        g = daily[cols].replace([np.inf, -np.inf], np.nan).dropna().copy()
        if len(g) < 30:
            rows.append({
                "context_id": context_id,
                "context_column": context_col,
                "days": int(len(g)),
                "eligible": False,
            })
            continue

        z_context = _zscore(g[context_col])
        z_breadth = _zscore(g["breadth_5d_centered"])
        interaction = z_context * z_breadth

        # SPY_5D_RETURN is already present as a baseline main effect. Likewise,
        # decline depth is an affine transform of the baseline SPY 20-day return.
        # In those two cases, add only the interaction term to avoid redundant
        # main-effect columns. This is algebraic de-duplication, not a research
        # specification change.
        redundant_main_effect = context_id in {
            "SPY_5D_RETURN",
            "SPY_20D_DECLINE_DEPTH",
        }

        design = [
            g["breadth_5d_centered"].to_numpy(float),
            g["spy_return_5d"].to_numpy(float),
            g["spy_return_20d_ctx"].to_numpy(float),
        ]
        names = ["breadth", "spy5", "spy20"]

        if not redundant_main_effect:
            design.append(z_context.to_numpy(float))
            names.append("context_z")

        design.append(interaction.to_numpy(float))
        names.append("breadth_x_context_z")

        fit = _ols(
            g["full_confounder_residual_ic"].to_numpy(float),
            np.column_stack(design),
            names,
        )
        rows.append({
            "context_id": context_id,
            "context_column": context_col,
            "days": int(len(g)),
            "eligible": True,
            "coef_breadth": fit["coef_breadth"],
            "t_breadth": fit["t_breadth"],
            "coef_context_z": fit.get("coef_context_z", np.nan),
            "t_context_z": fit.get("t_context_z", np.nan),
            "coef_breadth_x_context_z": fit["coef_breadth_x_context_z"],
            "t_breadth_x_context_z": fit["t_breadth_x_context_z"],
            "r2": fit["r2"],
        })
'''

    if old not in text:
        raise RuntimeError(
            "Expected V7 Phase 9 interaction block not found; no changes made."
        )

    PHASE9.write_text(text.replace(old, new, 1), encoding="utf-8")

    print("[APPLY] V7 Phase 9 duplicate context-column dimension fix")
    print("[APPLY] redundant SPY5/SPY20 context main effects removed algebraically")
    print()
    print("V7 Phase 9 dimension fix complete.")
    print("Research contract unchanged; this only fixes duplicate-column/collinearity handling.")
    print("The 2026-09-01+ holdout remains sealed. No portfolio simulation, freeze, or orders.")


if __name__ == "__main__":
    main()
