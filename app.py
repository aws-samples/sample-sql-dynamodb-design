import streamlit as st
import json
import os
import threading

st.set_page_config(page_title="SQL to DynamoDB Design Mentor", page_icon="🔄", layout="wide")

# --- File helpers ---

def load_json(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return None

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def load_md(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            return f.read()
    return None

# --- State init ---

if "current_step" not in st.session_state:
    st.session_state.current_step = 1
if "pipeline_running" not in st.session_state:
    st.session_state.pipeline_running = False
if "pipeline_log" not in st.session_state:
    st.session_state.pipeline_log = []
if "pipeline_done" not in st.session_state:
    st.session_state.pipeline_done = False
if "extracted" not in st.session_state:
    st.session_state.extracted = os.path.exists("access_patterns.md")

# --- Sidebar nav ---

st.sidebar.title("🔄 SQL to DynamoDB Design Mentor")
st.sidebar.caption("SQL Server → DynamoDB Migration")
st.sidebar.divider()

steps = {
    1: "📂 Project Setup",
    2: "🏗️ Entity Selection",
    3: "📏 Entity Metrics",
    4: "📊 Access Patterns",
    5: "🚀 Run Pipeline",
    6: "📋 Results",
}

for num, label in steps.items():
    if st.sidebar.button(label, key=f"nav_{num}", use_container_width=True,
                         type="primary" if st.session_state.current_step == num else "secondary"):
        st.session_state.current_step = num

# ============================================================
# STEP 1: Project Setup
# ============================================================

if st.session_state.current_step == 1:
    st.header("📂 Project Setup")
    st.write("Point to your .NET project to scan for data access patterns.")

    project_path = st.text_input(
        "Project path (relative to workspace)",
        value="sample-dotnet-project",
        help="Path to the .NET project folder containing .cs files"
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("🔍 Scan Project", type="primary", disabled=st.session_state.pipeline_running):
            if not project_path or not os.path.isdir(project_path):
                st.error(f"Directory not found: {project_path}")
            else:
                with st.spinner("Scanning .NET project and extracting access patterns..."):
                    from pipeline import extractor
                    extractor(f"Scan the .NET project at {project_path} and extract all access patterns into access_patterns.md")
                    st.session_state.extracted = True
                st.success("Extraction complete. access_patterns.md generated.")
                st.session_state.current_step = 2
                st.rerun()

    with col2:
        if os.path.exists("access_patterns.md"):
            if st.button("⏭️ Skip (use existing access_patterns.md)"):
                st.session_state.extracted = True
                st.session_state.current_step = 2
                st.rerun()

    if os.path.exists("access_patterns.md"):
        with st.expander("Preview access_patterns.md", expanded=False):
            st.markdown(load_md("access_patterns.md")[:3000] + "\n\n*... (truncated)*")

# ============================================================
# STEP 2: Entity Selection
# ============================================================

elif st.session_state.current_step == 2:
    st.header("🏗️ Entity Selection")

    if not st.session_state.extracted:
        st.warning("Run Step 1 first to extract access patterns.")
        st.stop()

    # Load entities from entity_metrics.json
    metrics = load_json("entity_metrics.json")
    if not metrics:
        st.error("entity_metrics.json not found. Run extraction first.")
        st.stop()

    all_entities = list(metrics.get("entities", {}).keys())

    # Load existing scope
    scope = load_json("migration_scope.json") or {
        "migration_mode": "full",
        "selected_entities": all_entities,
        "excluded_entities": []
    }

    st.write("Choose which entities to migrate to DynamoDB.")

    mode = st.radio(
        "Migration mode",
        options=["full", "microservice", "hybrid"],
        index=["full", "microservice", "hybrid"].index(scope.get("migration_mode", "full")),
        horizontal=True,
        help="**Full**: all entities. **Microservice**: subset for one service. **Hybrid**: subset migrates, SQL stays for rest."
    )

    if mode == "full":
        selected = all_entities
        st.info(f"All {len(all_entities)} entities will be migrated.")
    else:
        st.write("Select entities for this migration scope:")
        selected = []
        cols = st.columns(3)
        for i, entity in enumerate(all_entities):
            with cols[i % 3]:
                entity_data = metrics["entities"][entity]
                checked = entity in scope.get("selected_entities", all_entities)
                rel_info = entity_data.get("relationships", {})
                rel_str = ", ".join(f"{k} ({v})" for k, v in rel_info.items()) if rel_info else "None"
                if st.checkbox(
                    f"{entity} ({entity_data.get('average_row_size_kb', '?')} KB)",
                    value=checked,
                    key=f"entity_{entity}",
                    help=f"Table: {entity_data.get('sql_table', '?')} | Relations: {rel_str}"
                ):
                    selected.append(entity)

    excluded = [e for e in all_entities if e not in selected]

    # Show impact preview
    if selected and mode != "full":
        ap_data = metrics.get("access_patterns", {})
        in_scope_count = 0
        cross_count = 0
        excluded_count = 0
        selected_set = set(selected)
        for ap_id, ap in ap_data.items():
            entities = set(ap.get("source_entities", []))
            in_s = entities & selected_set
            out_s = entities - selected_set
            if not in_s:
                excluded_count += 1
            elif out_s:
                cross_count += 1
            else:
                in_scope_count += 1

        col1, col2, col3 = st.columns(3)
        col1.metric("In-scope patterns", in_scope_count)
        col2.metric("Cross-boundary", cross_count, help="Patterns referencing both in-scope and out-of-scope entities")
        col3.metric("Excluded", excluded_count)

    if st.button("💾 Save & Continue", type="primary"):
        scope_data = {
            "description": "Migration scope configuration.",
            "migration_mode": mode,
            "migration_mode_options": ["full", "microservice", "hybrid"],
            "selected_entities": selected,
            "excluded_entities": excluded,
        }
        save_json("migration_scope.json", scope_data)
        st.success(f"Saved: {len(selected)} entities selected ({mode} mode)")
        st.session_state.current_step = 3
        st.rerun()

# ============================================================
# STEP 3: Entity Metrics (avg item sizes)
# ============================================================

elif st.session_state.current_step == 3:
    st.header("📏 Entity Metrics")

    metrics = load_json("entity_metrics.json")
    scope = load_json("migration_scope.json")
    if not metrics or not scope:
        st.warning("Complete previous steps first.")
        st.stop()

    selected = scope.get("selected_entities", [])
    st.write("Review and adjust average row sizes for selected entities. These drive RCU/WCU capacity estimates.")

    updated_entities = {}
    for entity_name in selected:
        entity = metrics["entities"].get(entity_name)
        if not entity:
            continue

        with st.expander(f"**{entity_name}** — {entity.get('sql_table', '')} ({entity.get('average_row_size_kb', '?')} KB)", expanded=True):
            col1, col2 = st.columns([2, 1])
            with col1:
                st.caption(f"Fields: {entity.get('fields', 'N/A')}")
                st.caption(f"Estimated bytes: {entity.get('estimated_field_total_bytes', '?')} + ~100 overhead")
                rels = entity.get("relationships", {})
                if rels:
                    st.caption(f"Relationships: {', '.join(f'{k} ({v})' for k, v in rels.items())}")
            with col2:
                new_size = st.number_input(
                    f"Avg row size (KB)",
                    value=float(entity.get("average_row_size_kb", 0.5)),
                    min_value=0.01, max_value=400.0, step=0.05,
                    key=f"size_{entity_name}",
                    help="Average size of a single row in KB. Include DynamoDB overhead (~100 bytes)."
                )
                if "avg_items_per_parent" in entity:
                    new_avg = st.number_input(
                        f"Avg items per parent",
                        value=int(entity.get("avg_items_per_parent", 1)),
                        min_value=1, max_value=10000, step=1,
                        key=f"avg_{entity_name}"
                    )
                    entity["avg_items_per_parent"] = new_avg

            entity["average_row_size_kb"] = new_size
            updated_entities[entity_name] = entity

    if st.button("💾 Save & Continue", type="primary"):
        for name, data in updated_entities.items():
            metrics["entities"][name] = data
        save_json("entity_metrics.json", metrics)
        st.success("Entity metrics saved.")
        st.session_state.current_step = 4
        st.rerun()

# ============================================================
# STEP 4: Access Patterns (view + requests/hour)
# ============================================================

elif st.session_state.current_step == 4:
    st.header("📊 Access Patterns & Request Rates")

    metrics = load_json("entity_metrics.json")
    scope = load_json("migration_scope.json")
    if not metrics or not scope:
        st.warning("Complete previous steps first.")
        st.stop()

    selected_set = set(scope.get("selected_entities", []))
    mode = scope.get("migration_mode", "full")

    # Classify patterns
    read_patterns = metrics.get("access_patterns", {})
    write_patterns = metrics.get("write_patterns", {})

    def classify_pattern(entities_key, pattern_data):
        entities = set(pattern_data.get(entities_key, []))
        in_s = entities & selected_set
        out_s = entities - selected_set
        if not in_s:
            return "excluded"
        elif out_s:
            return "cross_boundary"
        return "in_scope"

    # --- Read patterns ---
    st.subheader("Read Patterns")
    st.caption("Set requests/hour for each access pattern based on your expected workload.")

    updated_reads = {}
    for ap_id in sorted(read_patterns.keys(), key=lambda x: int(x.split("-")[1])):
        ap = read_patterns[ap_id]
        classification = classify_pattern("source_entities", ap)
        if classification == "excluded" and mode != "full":
            continue

        badge = ""
        if classification == "cross_boundary":
            badge = " ⚠️"
        elif classification == "excluded":
            badge = " ⛔"

        entities_str = ", ".join(ap.get("source_entities", []))
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.markdown(f"**{ap_id}**: {ap['name']}{badge}")
            st.caption(f"{ap.get('operation', 'READ')} | Entities: {entities_str} | {ap.get('notes', '')}")
        with col2:
            new_rph = st.number_input(
                "req/hour", value=int(ap.get("requests_per_hour", 0)),
                min_value=0, max_value=1000000, step=100,
                key=f"rph_{ap_id}", label_visibility="collapsed"
            )
            ap["requests_per_hour"] = new_rph
        with col3:
            new_items = st.number_input(
                "avg items", value=int(ap.get("avg_items_returned", 1)),
                min_value=0, max_value=10000, step=1,
                key=f"items_{ap_id}", label_visibility="collapsed"
            )
            ap["avg_items_returned"] = new_items
        updated_reads[ap_id] = ap

    # --- Write patterns ---
    st.subheader("Write Patterns")

    updated_writes = {}
    for wp_id in sorted(write_patterns.keys(), key=lambda x: int(x.split("-")[1])):
        wp = write_patterns[wp_id]
        classification = classify_pattern("target_entities", wp)
        if classification == "excluded" and mode != "full":
            continue

        badge = " ⚠️" if classification == "cross_boundary" else ""
        entities_str = ", ".join(wp.get("target_entities", []))
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"**{wp_id}**: {wp['name']}{badge}")
            st.caption(f"WRITE | Entities: {entities_str} | {wp.get('notes', '')}")
        with col2:
            new_rph = st.number_input(
                "req/hour", value=int(wp.get("requests_per_hour", 0)),
                min_value=0, max_value=1000000, step=100,
                key=f"rph_{wp_id}", label_visibility="collapsed"
            )
            wp["requests_per_hour"] = new_rph
        updated_writes[wp_id] = wp

    if st.button("💾 Save & Continue", type="primary"):
        metrics["access_patterns"] = updated_reads
        metrics["write_patterns"] = updated_writes
        save_json("entity_metrics.json", metrics)
        st.success("Access pattern metrics saved.")
        st.session_state.current_step = 5
        st.rerun()

# ============================================================
# STEP 5: Run Pipeline
# ============================================================

elif st.session_state.current_step == 5:
    st.header("🚀 Run Pipeline")

    scope = load_json("migration_scope.json")
    metrics = load_json("entity_metrics.json")

    if not scope or not metrics:
        st.warning("Complete previous steps first.")
        st.stop()

    # Summary
    selected = scope.get("selected_entities", [])
    mode = scope.get("migration_mode", "full")

    st.subheader("Configuration Summary")
    col1, col2, col3 = st.columns(3)
    col1.metric("Migration Mode", mode.title())
    col2.metric("Entities", len(selected))
    col3.metric("Access Patterns", len(metrics.get("access_patterns", {})))

    with st.expander("Selected entities"):
        for e in selected:
            ed = metrics["entities"].get(e, {})
            st.write(f"- **{e}** ({ed.get('average_row_size_kb', '?')} KB)")

    # Pipeline options
    st.subheader("Pipeline Phases")
    run_extract = st.checkbox("Phase 1: Extract access patterns", value=False,
                              help="Re-scan .NET project. Uncheck to use existing access_patterns.md")
    run_model = st.checkbox("Phase 2: Design DynamoDB model", value=True)
    run_validate = st.checkbox("Phase 3: Validate patterns", value=True)
    run_metrics = st.checkbox("Phase 4: Capacity analysis", value=True)

    project_path = st.text_input("Project path (for Phase 1)", value="sample-dotnet-project") if run_extract else None

    if st.button("▶️ Run Pipeline", type="primary", disabled=st.session_state.pipeline_running):
        st.session_state.pipeline_running = True
        st.session_state.pipeline_done = False
        st.session_state.pipeline_log = []

        progress = st.progress(0, text="Starting pipeline...")
        log_area = st.empty()

        try:
            from pipeline import (
                extractor, architect, validator, metrics_analyzer,
                filter_access_patterns_by_scope, load_migration_scope
            )

            total_phases = sum([run_extract, run_model, run_validate, run_metrics])
            phase_num = 0

            # Phase 1
            if run_extract:
                phase_num += 1
                progress.progress(phase_num / total_phases, text="Phase 1: Extracting access patterns...")
                st.session_state.pipeline_log.append("Phase 1: Extracting access patterns...")
                log_area.code("\n".join(st.session_state.pipeline_log))
                extractor(f"Scan the .NET project at {project_path} and extract all access patterns into access_patterns.md")
                st.session_state.pipeline_log.append("  ✓ access_patterns.md generated")

            # Scope filtering
            scope_cfg = load_migration_scope()
            if scope_cfg:
                st.session_state.pipeline_log.append(f"Applying scope filter ({scope_cfg.get('migration_mode')} mode)...")
                log_area.code("\n".join(st.session_state.pipeline_log))
                summary = filter_access_patterns_by_scope(scope_cfg)
                st.session_state.pipeline_log.append(f"  ✓ Scope applied")
                ap_file = "scoped_access_patterns.md"
                metrics_file = "scoped_entity_metrics.json"
                scope_instruction = (
                    f" IMPORTANT: This is a scoped migration ({scope_cfg.get('migration_mode')} mode). "
                    f"Only these entities are in scope: {', '.join(scope_cfg['selected_entities'])}. "
                    f"Read {ap_file} (not access_patterns.md) for the filtered access patterns. "
                    f"Patterns marked CROSS-BOUNDARY reference entities outside the migration scope — "
                    f"design the DynamoDB model for the in-scope entities only and note that "
                    f"out-of-scope data must be fetched via API call or event sync."
                )
            else:
                ap_file = "access_patterns.md"
                metrics_file = "entity_metrics.json"
                scope_instruction = ""

            # Phase 2
            if run_model:
                phase_num += 1
                progress.progress(phase_num / total_phases, text="Phase 2: Designing DynamoDB model...")
                st.session_state.pipeline_log.append("Phase 2: Designing DynamoDB model...")
                log_area.code("\n".join(st.session_state.pipeline_log))
                architect(
                    f"Read {ap_file} and design the DynamoDB model.{scope_instruction} "
                    f"If {metrics_file} exists, read it and use the metrics to make data-driven modeling decisions. "
                    f"Write to dynamo_model.md and dynamo_model.json"
                )
                st.session_state.pipeline_log.append("  ✓ dynamo_model.md + dynamo_model.json generated")

            # Phase 3
            if run_validate:
                phase_num += 1
                progress.progress(phase_num / total_phases, text="Phase 3: Validating patterns...")
                st.session_state.pipeline_log.append("Phase 3: Validating patterns...")
                log_area.code("\n".join(st.session_state.pipeline_log))
                validator(
                    f"Read {ap_file} and dynamo_model.md. Validate coverage and classify each pattern.{scope_instruction} "
                    f"Write to validation_report.md"
                )
                st.session_state.pipeline_log.append("  ✓ validation_report.md generated")

            # Phase 4
            if run_metrics:
                phase_num += 1
                progress.progress(phase_num / total_phases, text="Phase 4: Analyzing capacity...")
                st.session_state.pipeline_log.append("Phase 4: Analyzing capacity metrics...")
                log_area.code("\n".join(st.session_state.pipeline_log))
                metrics_analyzer(
                    f"Read {metrics_file}, {ap_file}, and dynamo_model.md. "
                    f"Analyze RCU/WCU for each modeling strategy and produce capacity_analysis.md"
                )
                st.session_state.pipeline_log.append("  ✓ capacity_analysis.md generated")

            progress.progress(1.0, text="Pipeline complete!")
            st.session_state.pipeline_log.append("\n✅ Pipeline complete!")
            log_area.code("\n".join(st.session_state.pipeline_log))
            st.session_state.pipeline_done = True

        except Exception as e:
            st.session_state.pipeline_log.append(f"\n❌ Error: {str(e)}")
            log_area.code("\n".join(st.session_state.pipeline_log))
            st.error(f"Pipeline failed: {e}")
        finally:
            st.session_state.pipeline_running = False

    if st.session_state.pipeline_done:
        if st.button("📋 View Results →", type="primary"):
            st.session_state.current_step = 6
            st.rerun()

# ============================================================
# STEP 6: Results
# ============================================================

elif st.session_state.current_step == 6:
    st.header("📋 Migration Results")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "DynamoDB Model", "Access Pattern Mapping", "Validation Report", "Capacity Analysis", "Raw JSON"
    ])

    with tab1:
        md_content = load_md("dynamo_model.md")
        if md_content:
            st.markdown(md_content)
        else:
            st.info("dynamo_model.md not generated yet. Run the pipeline first.")

    with tab2:
        model_json = load_json("dynamo_model.json")
        if model_json and "accessPatternMapping" in model_json:
            patterns = model_json["accessPatternMapping"]
            st.write(f"**{len(patterns)} access patterns mapped**")

            for ap in patterns:
                pattern_id = ap.get("pattern", "")
                name = ap.get("name", "")
                index = ap.get("index", "")
                pk = ap.get("pk", "")
                sk = ap.get("sk_condition", "")
                filt = ap.get("filter", "None")
                note = ap.get("note", "")

                with st.expander(f"{pattern_id}: {name} — {index}", expanded=False):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**Key Condition**")
                        st.code(f"PK = {pk}\nSK: {sk}", language="text")
                        if filt and filt != "None":
                            st.markdown("**Filter**")
                            st.code(filt, language="text")
                        if note:
                            st.caption(note)
                    with col2:
                        orig = ap.get("original_code", "")
                        dynamo = ap.get("dynamodb_query", "")
                        if orig:
                            st.markdown("**Original (C#)**")
                            st.code(orig, language="csharp")
                        if dynamo:
                            st.markdown("**DynamoDB (Python)**")
                            st.code(dynamo, language="python")
        else:
            st.info("dynamo_model.json not generated yet. Run the pipeline first.")

    with tab3:
        val_content = load_md("validation_report.md")
        if val_content:
            st.markdown(val_content)
        else:
            st.info("validation_report.md not generated yet. Run the pipeline first.")

    with tab4:
        cap_content = load_md("capacity_analysis.md")
        if cap_content:
            st.markdown(cap_content)
        else:
            st.info("capacity_analysis.md not generated yet. Run the pipeline with Phase 4 enabled.")

    with tab5:
        model_json = load_json("dynamo_model.json")
        if model_json:
            st.json(model_json)
        else:
            st.info("No JSON output yet.")

    st.divider()
    st.caption("Need to adjust? Use the sidebar to go back to any step and re-run.")
