# The PIM window

Double-click **`PIM.bat`** in the repo folder. It opens http://127.0.0.1:8766/ in your browser
(local only; nothing leaves your machine). Close the black console window to stop it.
Or: `cd` to the repo and run `python -m pim.cli.main ui`.

The window is a front for the same commands — it only ever writes the YAML files the build
reads (`brands/<brand>/`) and runs the same build. Nothing is hidden in the window.

```
 1 Brand & files ─► 2 What changed ─► 3 Build ─► 4 Decide ─► 5 Derive & review ─► 6 Publish
   write the pack     fingerprints       versions    CSV loop      (M2)              (M3–M5)
   (lists files,      vs last build      + compare   + decisions
   previews rows,                                    (M2)
   picks columns)
```

| Stage | What you do there | Writes |
|---|---|---|
| 1 Brand & files | Name the brand, point at its folder, list the files, click the header row and the part-number column per file, tick the columns to keep and name them, pick the roster file. The YAML on the right updates as you go. **Validate → Save pack.** | `brands/<slug>/*.yaml` |
| 2 What changed | Re-reads every file and compares fingerprints with the last build: unchanged / changed / new / missing. | nothing |
| 3 Build | Dry run or Build. Shows gates (PASS/FAIL with measured numbers), per-field coverage, notes. Lists versions; **Compare** two versions product-by-product, field-by-field. | `var/<slug>/pim.db`, `exports/<build>/` |
| 4 Decide | Export fields to CSV → edit in Excel → Preview changes (every cell, before→after; damage refused) → Apply (reversible overrides) → Build again. | `brands/<slug>/overrides/*.yaml` |
| 5, 6 | Planned (M2, M3–M5). Shown so the whole path is visible. | — |

Things the window does not edit (yet): two-block sheets (`blocks:` in sources.yaml) and the
price-book code pairs (`joins.yaml → associations`). It shows them and leaves them as written.

Command-line equivalents: `validate-pack`, `status`, `build`, `builds`, `diff`, `export-csv`, `import-csv`.
