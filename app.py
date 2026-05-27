import streamlit as st
import pandas as pd
import numpy as np
from fpdf import FPDF
from datetime import datetime
import re

st.set_page_config(page_title="Universal Inventory Manager", layout="wide")
st.title("📦 Universal Inventory Transfer System")
st.markdown("**Auto‑detects columns – manual override available**")

# ============================================
# HELPER FUNCTIONS
# ============================================

def clean_text(text):
    if pd.isna(text):
        return ""
    text = str(text)
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    return text.strip()

def get_brand(product):
    return "Boys" if "BOYS" in product.upper() else ("Girls" if "GIRLS" in product.upper() else "Unisex")

def table_to_pdf(df, title, landscape=False):
    if df.empty:
        return None
    pdf = FPDF()
    pdf.add_page(orientation='L' if landscape else 'P')
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(200, 10, clean_text(title), ln=True, align='C')
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 8)
    cols = df.columns.tolist()
    widths = [max(20, min(40, len(str(c))*3)) for c in cols]
    for i, col in enumerate(cols):
        pdf.cell(widths[i], 8, clean_text(col), 1, 0, 'C')
    pdf.ln()
    pdf.set_font("Arial", size=7)
    for _, row in df.iterrows():
        for i, col in enumerate(cols):
            txt = clean_text(str(row[col]))[:30]
            pdf.cell(widths[i], 7, txt, 1, 0, 'L')
        pdf.ln()
    return pdf.output(dest='S').encode('latin-1', errors='ignore')

# ============================================
# IMPROVED AUTO‑DETECTION + MANUAL OVERRIDE
# ============================================

def auto_detect_columns(df):
    """Return (branch_col, desc_col, qty_col) with improved logic."""
    desc_col = None
    branch_col = None
    qty_col = None

    # 1. Find description column (contains " - ")
    for col in df.columns:
        if df[col].astype(str).str.contains(" - ").any():
            desc_col = col
            break

    # 2. Find branch column – prefer column with many distinct branch names
    branch_keywords = ["POPULAR SHOE COMPANY", "PRAGATHI SHOES AMD 2", "PRAGATHI SHOES RAGOLU",
                       "PRAGATHI SHOES BALAGA", "PRAGATHI SHOES AKP", "PRAGATHI SHOES",
                       "POPULAR", "AMD 2", "RAGOLU", "BALAGA", "AKP"]
    best_score = 0
    for col in df.columns:
        if col == desc_col:
            continue
        # Count rows that contain any branch keyword
        mask = df[col].astype(str).str.contains('|'.join(branch_keywords), case=False, na=False)
        score = mask.sum()
        # Count distinct branch names in this column (higher is better)
        distinct = df[col].astype(str).unique()
        distinct_matches = sum(1 for v in distinct if any(kw in v for kw in branch_keywords))
        score += distinct_matches * 10
        if score > best_score:
            best_score = score
            branch_col = col
    if branch_col is None:
        branch_col = df.columns[0]   # fallback

    # 3. Find quantity column (numeric, not desc or branch)
    for col in df.columns:
        if col in [desc_col, branch_col]:
            continue
        if pd.api.types.is_numeric_dtype(df[col]) or df[col].dtype == 'float64':
            qty_col = col
            break
    if qty_col is None:
        # fallback to last column
        qty_col = df.columns[-1]

    return branch_col, desc_col, qty_col

def parse_csv_with_columns(df, branch_col, desc_col, qty_col):
    """Parse using given column names."""
    items = []
    for _, row in df.iterrows():
        branch = str(row[branch_col]).strip()
        desc = str(row[desc_col]).strip()
        if " - " not in desc:
            continue
        try:
            qty = float(row[qty_col])
        except:
            qty = 0
        if qty < 0:
            qty = 0
        parts = desc.split(" - ")
        if len(parts) >= 5:
            items.append({
                "Branch": branch,
                "Product": parts[0].strip(),
                "Colour": parts[1].strip(),
                "Size": parts[2].strip(),
                "Article": parts[3].strip(),
                "MRP": parts[4].strip(),
                "Quantity": qty
            })
    return items

def build_inventory(items):
    if not items:
        return None, None, []
    df_items = pd.DataFrame(items)
    df_items['SKU'] = df_items.apply(lambda x: f"{x['Product']}|{x['Colour']}|{x['Size']}|{x['Article']}|{x['MRP']}", axis=1)
    all_skus = df_items['SKU'].unique()
    branches = df_items['Branch'].unique().tolist()
    inv = {}
    for branch in branches:
        branch_data = df_items[df_items['Branch'] == branch]
        sku_dict = {row['SKU']: row['Quantity'] for _, row in branch_data.iterrows()}
        records = []
        for sku in all_skus:
            sku_row = df_items[df_items['SKU'] == sku].iloc[0]
            q = sku_dict.get(sku, 0)
            records.append({
                "Branch": branch,
                "SKU": sku,
                "Product": sku_row['Product'],
                "Colour": sku_row['Colour'],
                "Size": sku_row['Size'],
                "Article": sku_row['Article'],
                "MRP": sku_row['MRP'],
                "Quantity": q,
                "Brand": get_brand(sku_row['Product'])
            })
        inv[branch] = pd.DataFrame(records)
    return inv, all_skus, branches

# ============================================
# TRANSFER LOGIC (unchanged)
# ============================================

def calculate_transfers(inv, targets):
    transfers = []
    if not inv:
        return pd.DataFrame()
    first_branch = next(iter(inv.values()))
    if first_branch.empty:
        return pd.DataFrame()
    all_skus = first_branch['SKU'].unique()
    for sku in all_skus:
        stock = {}
        details = {}
        for branch, df in inv.items():
            row = df[df['SKU'] == sku]
            if not row.empty:
                q = row['Quantity'].iloc[0]
                stock[branch] = q
                if not details:
                    details = {
                        "Product": row['Product'].iloc[0],
                        "Colour": row['Colour'].iloc[0],
                        "Size": row['Size'].iloc[0],
                        "Article": row['Article'].iloc[0],
                        "MRP": row['MRP'].iloc[0],
                        "Brand": row['Brand'].iloc[0]
                    }
            else:
                stock[branch] = 0
        if not details:
            continue
        surplus = []
        deficit = []
        for branch, qty in stock.items():
            target = targets.get(branch, 8)
            if qty > target:
                surplus.append({"branch": branch, "excess": qty - target, "current": qty})
            elif qty < target:
                deficit.append({"branch": branch, "need": target - qty, "current": qty})
        for s in surplus:
            rem = s["excess"]
            for d in deficit[:]:
                if rem <= 0:
                    break
                transfer = min(rem, d["need"])
                if transfer > 0:
                    transfers.append({
                        "SKU": sku,
                        "Product": details['Product'],
                        "Colour": details['Colour'],
                        "Size": details['Size'],
                        "Article": details['Article'],
                        "MRP": details['MRP'],
                        "Brand": details['Brand'],
                        "From Branch": s["branch"],
                        "To Branch": d["branch"],
                        "Transfer Qty": transfer,
                        "Reason": f"From {s['branch']} to {d['branch']}"
                    })
                    rem -= transfer
                    d["need"] -= transfer
                    if d["need"] <= 0:
                        deficit.remove(d)
            s["excess"] = rem
    return pd.DataFrame(transfers) if transfers else pd.DataFrame()

def get_branch_transfers(transfers_df, branch):
    if transfers_df.empty:
        return pd.DataFrame()
    out = transfers_df[transfers_df['From Branch'] == branch]
    inc = transfers_df[transfers_df['To Branch'] == branch]
    return pd.concat([out, inc]) if not out.empty or not inc.empty else pd.DataFrame()

# ============================================
# SESSION STATE
# ============================================

if "loaded" not in st.session_state:
    st.session_state.loaded = False
    st.session_state.inv = {}
    st.session_state.branches = []
    st.session_state.targets = {}
    st.session_state.transfers = pd.DataFrame()
    st.session_state.file_name = None
    st.session_state.df_raw = None
    st.session_state.auto_branch = None
    st.session_state.auto_desc = None
    st.session_state.auto_qty = None

# ============================================
# SIDEBAR
# ============================================

with st.sidebar:
    st.header("⚙️ Configuration")
    uploaded = st.file_uploader("Upload any Inventory CSV", type=["csv"])
    st.divider()

    if st.session_state.loaded and st.session_state.df_raw is not None:
        st.subheader("Manual Column Override")
        use_manual = st.checkbox("Use manual column selection (if auto‑detection is wrong)")
        if use_manual:
            cols = st.session_state.df_raw.columns.tolist()
            branch_manual = st.selectbox("Branch column", cols, index=cols.index(st.session_state.auto_branch) if st.session_state.auto_branch in cols else 0)
            desc_manual = st.selectbox("Description column (contains ' - ')", cols, index=cols.index(st.session_state.auto_desc) if st.session_state.auto_desc in cols else 0)
            qty_manual = st.selectbox("Quantity column (numeric)", cols, index=cols.index(st.session_state.auto_qty) if st.session_state.auto_qty in cols else 0)
            if st.button("Re‑parse with selected columns"):
                items = parse_csv_with_columns(st.session_state.df_raw, branch_manual, desc_manual, qty_manual)
                if not items:
                    st.error("No items found with those columns.")
                else:
                    inv, _, branches = build_inventory(items)
                    if inv is None:
                        st.stop()
                    targets = {b: 8 for b in branches}
                    transfers = calculate_transfers(inv, targets)
                    st.session_state.inv = inv
                    st.session_state.branches = branches
                    st.session_state.targets = targets
                    st.session_state.transfers = transfers
                    st.success(f"Reloaded {len(items)} rows from {len(branches)} branches.")
                    st.rerun()
        else:
            st.info(f"Auto‑detected branch: `{st.session_state.auto_branch}`\nDescription: `{st.session_state.auto_desc}`\nQuantity: `{st.session_state.auto_qty}`")

    st.divider()
    if st.session_state.loaded and st.session_state.branches:
        st.subheader("Branch Targets")
        for b in st.session_state.branches:
            cur = st.session_state.targets.get(b, 8)
            new = st.number_input(f"{b}", min_value=1, max_value=50, value=cur, key=f"tgt_{b}")
            if new != cur:
                st.session_state.targets[b] = new
                st.session_state.transfers = calculate_transfers(st.session_state.inv, st.session_state.targets)
                st.rerun()
    if st.button("🔄 Reset All Data"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

# ============================================
# MAIN APP
# ============================================

if uploaded:
    if st.session_state.file_name != uploaded.name or not st.session_state.loaded:
        with st.spinner("Loading and auto‑detecting columns..."):
            df = pd.read_csv(uploaded)
            branch_col, desc_col, qty_col = auto_detect_columns(df)
            st.session_state.df_raw = df
            st.session_state.auto_branch = branch_col
            st.session_state.auto_desc = desc_col
            st.session_state.auto_qty = qty_col
            items = parse_csv_with_columns(df, branch_col, desc_col, qty_col)
            if not items:
                st.error("Auto‑detection failed to find any product rows. Please use manual column selection.")
                st.session_state.loaded = False
                st.stop()
            inv, _, branches = build_inventory(items)
            if inv is None:
                st.stop()
            targets = {b: 8 for b in branches}
            transfers = calculate_transfers(inv, targets)
            st.session_state.inv = inv
            st.session_state.branches = branches
            st.session_state.targets = targets
            st.session_state.transfers = transfers
            st.session_state.file_name = uploaded.name
            st.session_state.loaded = True
            st.success(f"Loaded {len(items)} product rows from {len(branches)} branches.\n"
                       f"Auto‑detected branch column: `{branch_col}`")
            st.rerun()

if st.session_state.loaded and st.session_state.branches:
    inv = st.session_state.inv
    branches = st.session_state.branches
    targets = st.session_state.targets
    transfers = st.session_state.transfers

    # Branch needs (shortage)
    needs = {b: max(0, targets[b] - inv[b]['Quantity'].sum()) for b in branches}

    tab_names = ["📊 Dashboard", "🚚 All Transfers", "📋 Zero Stock Anywhere"] + [f"🏪 {b}" for b in branches]
    tabs = st.tabs(tab_names)

    # Dashboard
    with tabs[0]:
        st.subheader("Branch‑wise Stock Needed")
        need_df = pd.DataFrame(list(needs.items()), columns=["Branch", "Units Needed"]).sort_values("Units Needed", ascending=False)
        st.dataframe(need_df, use_container_width=True)
        if st.button("📄 Branch Needs PDF"):
            pdf = table_to_pdf(need_df, "Branch-wise Stock Needed")
            if pdf:
                st.download_button("Download", pdf, "branch_needs.pdf")
        st.markdown("---")
        st.subheader("Branch Stock Summary")
        summary = []
        for b in branches:
            df = inv[b]
            tgt = targets[b]
            tot = int(df['Quantity'].sum())
            target_tot = tgt * len(df)
            summary.append({
                "Branch": b,
                "Total Stock": tot,
                "Target Total": target_tot,
                "Shortage": max(0, target_tot - tot),
                "Surplus": max(0, tot - target_tot),
                "Zero SKUs": len(df[df['Quantity'] == 0]),
                "Low SKUs": len(df[(df['Quantity'] > 0) & (df['Quantity'] < tgt)])
            })
        sum_df = pd.DataFrame(summary)
        st.dataframe(sum_df, use_container_width=True)
        if st.button("📄 Branch Summary PDF"):
            pdf = table_to_pdf(sum_df, "Branch Summary")
            if pdf:
                st.download_button("Download", pdf, "branch_summary.pdf")

    # All Transfers
    with tabs[1]:
        if not transfers.empty:
            disp = transfers[['From Branch', 'To Branch', 'Product', 'Size', 'Colour', 'Article', 'MRP', 'Transfer Qty']]
            st.dataframe(disp, use_container_width=True)
            if st.button("📄 All Transfers PDF"):
                pdf = table_to_pdf(disp, "All Suggested Transfers", landscape=True)
                if pdf:
                    st.download_button("Download", pdf, "all_transfers.pdf")
        else:
            st.success("No transfers needed.")

    # Zero Stock Anywhere
    with tabs[2]:
        zero_all = []
        first_branch = branches[0]
        if not inv[first_branch].empty:
            for sku in inv[first_branch]['SKU'].unique():
                total = 0
                info = None
                for b in branches:
                    row = inv[b][inv[b]['SKU'] == sku]
                    if not row.empty:
                        total += row['Quantity'].iloc[0]
                        if info is None:
                            info = {
                                "Product": row['Product'].iloc[0],
                                "Colour": row['Colour'].iloc[0],
                                "Size": row['Size'].iloc[0],
                                "Brand": row['Brand'].iloc[0],
                                "Article": row['Article'].iloc[0],
                                "MRP": row['MRP'].iloc[0]
                            }
                if total == 0 and info:
                    zero_all.append(info)
        zero_df = pd.DataFrame(zero_all)
        if not zero_df.empty:
            st.error(f"{len(zero_df)} products have zero stock in all branches")
            st.dataframe(zero_df[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP']], use_container_width=True)
            if st.button("📄 Zero Anywhere PDF"):
                pdf = table_to_pdf(zero_df[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP']],
                                   "Products with Zero Stock Across All Branches")
                if pdf:
                    st.download_button("Download", pdf, "zero_anywhere.pdf")
        else:
            st.success("Every product has stock in at least one branch.")

    # Branch‑specific tabs
    for idx, branch in enumerate(branches):
        with tabs[idx+3]:
            branch_df = inv[branch].copy()
            if branch_df.empty:
                st.info(f"No data for {branch}")
                continue
            tgt = targets[branch]
            min_level = max(1, tgt // 2)

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Total Stock", int(branch_df['Quantity'].sum()))
            c2.metric("SKUs", len(branch_df))
            c3.metric("Zero Stock", len(branch_df[branch_df['Quantity'] == 0]))
            c4.metric("Low Stock", len(branch_df[(branch_df['Quantity'] > 0) & (branch_df['Quantity'] < min_level)]))
            c5.metric("Surplus", len(branch_df[branch_df['Quantity'] > tgt]))

            st.subheader("Table 1: Zero Stock Items")
            zero = branch_df[branch_df['Quantity'] == 0].copy()
            if not zero.empty:
                search = st.text_input(f"🔍 Search Article", key=f"search_{branch}")
                if search:
                    zero = zero[zero['Article'].str.contains(search, case=False, na=False)]
                disp_zero = zero[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP']].reset_index(drop=True)
                disp_zero.insert(0, "Select", False)
                edited = st.data_editor(
                    disp_zero,
                    column_config={"Select": st.column_config.CheckboxColumn("Select")},
                    disabled=['Product','Brand','Size','Colour','Article','MRP'],
                    hide_index=True,
                    key=f"zero_edit_{branch}"
                )
                selected = edited[edited['Select'] == True]['Article'].tolist()
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"🗑️ Delete Selected", key=f"del_{branch}"):
                        if selected:
                            new_df = branch_df[~branch_df['Article'].isin(selected)]
                            st.session_state.inv[branch] = new_df
                            st.session_state.transfers = calculate_transfers(st.session_state.inv, targets)
                            st.success(f"Deleted {len(selected)} item(s) from {branch}")
                            st.rerun()
                        else:
                            st.warning("No items selected")
                with col2:
                    if st.button(f"🔄 Reset Branch", key=f"reset_{branch}"):
                        st.session_state.inv[branch] = inv[branch].copy()
                        st.session_state.transfers = calculate_transfers(st.session_state.inv, targets)
                        st.success(f"Reset {branch} to original")
                        st.rerun()
                if st.button(f"📄 PDF - Zero Stock", key=f"zero_pdf_{branch}"):
                    pdf = table_to_pdf(zero[['Product','Brand','Size','Colour','Article','MRP']], f"{branch} - Zero Stock")
                    if pdf:
                        st.download_button("Download", pdf, f"{branch}_zero.pdf")
            else:
                st.success("No zero stock items")

            st.subheader("Table 2: Low Stock Items")
            low = branch_df[(branch_df['Quantity'] > 0) & (branch_df['Quantity'] < min_level)].copy()
            if not low.empty:
                low_disp = low[['Product','Brand','Size','Colour','Article','MRP','Quantity']].copy()
                low_disp.rename(columns={'Quantity':'Currently Available'}, inplace=True)
                low_disp['Target'] = tgt
                st.dataframe(low_disp, use_container_width=True)
                if st.button(f"📄 PDF - Low Stock", key=f"low_pdf_{branch}"):
                    pdf = table_to_pdf(low_disp, f"{branch} - Low Stock Items")
                    if pdf:
                        st.download_button("Download", pdf, f"{branch}_low.pdf")
            else:
                st.success("No low stock items")

            st.subheader("Table 3: Complete Inventory")
            full = branch_df[['Product','Brand','Size','Colour','Article','MRP','Quantity']].copy()
            full.rename(columns={'Quantity':'Currently Available'}, inplace=True)
            full['Status'] = full['Currently Available'].apply(
                lambda x: 'Zero' if x==0 else ('Low' if x<min_level else ('Surplus' if x>tgt else 'OK'))
            )
            st.dataframe(full, use_container_width=True)
            if st.button(f"📄 PDF - Complete Inventory", key=f"full_pdf_{branch}"):
                pdf = table_to_pdf(full, f"{branch} - Complete Inventory", landscape=True)
                if pdf:
                    st.download_button("Download", pdf, f"{branch}_full.pdf")

            br_trans = get_branch_transfers(transfers, branch)
            if not br_trans.empty:
                st.subheader("Suggested Transfers")
                disp = br_trans[['Product','Brand','Size','Colour','From Branch','To Branch','Transfer Qty']]
                st.dataframe(disp, use_container_width=True)
                if st.button(f"📄 PDF - Transfers", key=f"trans_pdf_{branch}"):
                    pdf = table_to_pdf(disp, f"{branch} - Transfer Orders", landscape=True)
                    if pdf:
                        st.download_button("Download", pdf, f"{branch}_transfers.pdf")

else:
    st.info("👈 Upload any inventory CSV file")
    st.markdown("""
    ## Universal Inventory Transfer System

    **Works with any CSV** that contains:
    - A column with product descriptions in the format: `Product - Colour - Size - Article - MRP`
    - A column with branch/store names
    - A column with quantities (numeric)

    ### Features
    - **Auto‑detects** columns (branch, description, quantity)
    - **Manual override** if auto‑detection picks the wrong column (check the sidebar after upload)
    - Branch‑wise stock needed analysis
    - Intelligent transfers (surplus → deficit, including warehouse)
    - Zero stock table – search by article, multi‑select delete (affects only that branch), reset
    - PDF reports for every table
    """)
