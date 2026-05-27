import streamlit as st
import pandas as pd
import numpy as np
from fpdf import FPDF
from datetime import datetime
import re
import csv
import io

st.set_page_config(page_title="Universal Inventory Transfer System", layout="wide")

st.title("📦 Universal Inventory Transfer System")
st.markdown("**Works with any CSV containing product descriptions like `Product - Colour - Size - Article - MRP`**")

# ============================================
# BRANCH CONFIGURATION
# ============================================

KNOWN_BRANCHES = [
    "POPULAR SHOE COMPANY", "PRAGATHI SHOES AMD 2", "PRAGATHI SHOES RAGOLU",
    "PRAGATHI SHOES BALAGA", "PRAGATHI SHOES AKP", "PRAGATHI SHOES",
    "POPULAR", "AMD 2", "RAGOLU", "BALAGA", "AKP", "WAREHOUSE"
]

def clean_text(text):
    if pd.isna(text):
        return ""
    text = str(text)
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    text = text.replace('→', '->')
    return text.strip()

def get_brand(product):
    return "Boys" if "BOYS" in product.upper() else ("Girls" if "GIRLS" in product.upper() else "Unisex")

# ============================================
# UNIVERSAL CSV PARSER (handles any layout)
# ============================================

def read_csv_rows(uploaded_file):
    content = uploaded_file.getvalue().decode('utf-8', errors='ignore')
    # Try to detect delimiter
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(content[:500])
        delimiter = dialect.delimiter
    except:
        delimiter = ','
    csv_reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    return list(csv_reader)

def auto_detect_columns(rows):
    """Find description, branch, and quantity columns by scanning."""
    if not rows:
        return None, None, None
    # Skip possible header rows: find first row containing " - "
    data_start = 0
    for i, row in enumerate(rows):
        if any(" - " in cell for cell in row):
            data_start = i
            break
    # Use that row to detect columns
    sample = rows[data_start]
    desc_col = None
    branch_col = None
    qty_col = None
    for col in range(len(sample)):
        if " - " in sample[col]:
            desc_col = col
        if any(branch in sample[col] for branch in KNOWN_BRANCHES):
            branch_col = col
        try:
            val = float(sample[col])
            if val >= 0 and col != desc_col:
                qty_col = col
        except:
            pass
    # Fallback heuristics
    if desc_col is None:
        for row in rows[data_start:data_start+5]:
            for col in range(len(row)):
                if " - " in row[col]:
                    desc_col = col
                    break
            if desc_col is not None:
                break
    if branch_col is None and desc_col is not None:
        branch_col = desc_col - 1 if desc_col > 0 else 0
    if qty_col is None and desc_col is not None:
        qty_col = desc_col + 1 if desc_col + 1 < len(sample) else len(sample)-1
    return branch_col, desc_col, qty_col, data_start

def parse_any_csv(rows):
    branch_col, desc_col, qty_col, start = auto_detect_columns(rows)
    if None in (branch_col, desc_col, qty_col):
        return []
    items = []
    for row in rows[start:]:
        if len(row) <= max(branch_col, desc_col, qty_col):
            continue
        branch = row[branch_col].strip()
        desc = row[desc_col].strip()
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

def build_inventory(all_items):
    if not all_items:
        return None, None, []
    df_items = pd.DataFrame(all_items)
    df_items['SKU'] = df_items.apply(lambda x: f"{x['Product']}|{x['Colour']}|{x['Size']}|{x['Article']}|{x['MRP']}", axis=1)
    all_skus = df_items['SKU'].unique()
    unique_branches = df_items['Branch'].unique()
    complete_inventory = {}
    for branch in unique_branches:
        branch_data = df_items[df_items['Branch'] == branch]
        sku_dict = {row['SKU']: row['Quantity'] for _, row in branch_data.iterrows()}
        records = []
        for sku in all_skus:
            sku_row = df_items[df_items['SKU'] == sku].iloc[0]
            quantity = sku_dict.get(sku, 0)
            records.append({
                "Branch": branch,
                "SKU": sku,
                "Product": sku_row['Product'],
                "Colour": sku_row['Colour'],
                "Size": sku_row['Size'],
                "Article": sku_row['Article'],
                "MRP": sku_row['MRP'],
                "Quantity": quantity,
                "Brand": get_brand(sku_row['Product'])
            })
        complete_inventory[branch] = pd.DataFrame(records)
    return complete_inventory, all_skus, list(unique_branches)

# ============================================
# TRANSFER LOGIC (warehouse = "PRAGATHI SHOES")
# ============================================

def calculate_transfers(complete_inventory, branch_targets):
    all_transfers = []
    if not complete_inventory:
        return pd.DataFrame()
    first_branch = next(iter(complete_inventory.values()))
    if first_branch.empty:
        return pd.DataFrame()
    all_skus = first_branch['SKU'].unique()
    for sku in all_skus:
        branch_stock = {}
        sku_details = {}
        for branch, df in complete_inventory.items():
            row = df[df['SKU'] == sku]
            if not row.empty:
                qty = row['Quantity'].iloc[0]
                branch_stock[branch] = qty
                if not sku_details:
                    sku_details = {
                        "Product": row['Product'].iloc[0],
                        "Colour": row['Colour'].iloc[0],
                        "Size": row['Size'].iloc[0],
                        "Article": row['Article'].iloc[0],
                        "MRP": row['MRP'].iloc[0],
                        "Brand": row['Brand'].iloc[0]
                    }
            else:
                branch_stock[branch] = 0
        if not sku_details:
            continue
        surplus = []
        deficit = []
        for branch, stock in branch_stock.items():
            target = branch_targets.get(branch, 8)
            if stock > target:
                surplus.append({"branch": branch, "surplus": stock - target, "current": stock})
            elif stock < target:
                deficit.append({"branch": branch, "needed": target - stock, "current": stock})
        for s in surplus:
            rem = s["surplus"]
            for d in deficit[:]:
                if rem <= 0:
                    break
                transfer = min(rem, d["needed"])
                if transfer > 0:
                    all_transfers.append({
                        "SKU": sku,
                        "Product": sku_details['Product'],
                        "Colour": sku_details['Colour'],
                        "Size": sku_details['Size'],
                        "Article": sku_details['Article'],
                        "MRP": sku_details['MRP'],
                        "Brand": sku_details['Brand'],
                        "From Branch": s["branch"],
                        "From Current": s["current"],
                        "To Branch": d["branch"],
                        "To Current": d["current"],
                        "Transfer Qty": transfer,
                        "Reason": f"Surplus from {s['branch']} to {d['branch']}"
                    })
                    rem -= transfer
                    d["needed"] -= transfer
                    if d["needed"] <= 0:
                        deficit.remove(d)
            s["surplus"] = rem
    return pd.DataFrame(all_transfers) if all_transfers else pd.DataFrame()

def get_branch_transfers(transfers_df, branch):
    if transfers_df.empty:
        return pd.DataFrame()
    out = transfers_df[transfers_df['From Branch'] == branch]
    inc = transfers_df[transfers_df['To Branch'] == branch]
    return pd.concat([out, inc]) if not out.empty or not inc.empty else pd.DataFrame()

# ============================================
# PDF GENERATION (one function for any table)
# ============================================

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
# SESSION STATE INIT
# ============================================

if "inventory_loaded" not in st.session_state:
    st.session_state.inventory_loaded = False
    st.session_state.complete_inventory = {}
    st.session_state.inventory_data = {}
    st.session_state.branches = []
    st.session_state.branch_targets = {}
    st.session_state.transfers_df = pd.DataFrame()
    st.session_state.file_name = None

# ============================================
# SIDEBAR
# ============================================

with st.sidebar:
    st.header("⚙️ Configuration")
    uploaded_file = st.file_uploader("📁 Upload Inventory CSV (any format)", type=["csv"])
    st.divider()
    if st.session_state.inventory_loaded and st.session_state.branches:
        st.subheader("Branch Targets")
        for branch in st.session_state.branches:
            current = st.session_state.branch_targets.get(branch, 8)
            new = st.number_input(f"Target for {branch}", min_value=1, max_value=50, value=current, key=f"target_{branch}")
            if new != current:
                st.session_state.branch_targets[branch] = new
                st.session_state.transfers_df = calculate_transfers(st.session_state.inventory_data, st.session_state.branch_targets)
                st.rerun()
    if st.button("🔄 Reset All Data"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# ============================================
# MAIN APP
# ============================================

if uploaded_file:
    if st.session_state.file_name != uploaded_file.name or not st.session_state.inventory_loaded:
        with st.spinner("Parsing file (auto‑detect columns)..."):
            rows = read_csv_rows(uploaded_file)
            items = parse_any_csv(rows)
            if not items:
                st.error("No product rows found. Ensure the file contains a column with ' - '.")
                st.stop()
            complete_inv, all_skus, branches = build_inventory(items)
            if complete_inv is None:
                st.stop()
            targets = {b: 8 for b in branches}
            transfers = calculate_transfers(complete_inv, targets)
            st.session_state.complete_inventory = complete_inv
            st.session_state.inventory_data = complete_inv.copy()
            st.session_state.branches = branches
            st.session_state.branch_targets = targets
            st.session_state.transfers_df = transfers
            st.session_state.file_name = uploaded_file.name
            st.session_state.inventory_loaded = True
            st.success(f"✅ Loaded {len(items)} product rows from {len(branches)} branches.")
            st.rerun()
    
    if st.session_state.inventory_loaded and st.session_state.branches:
        complete_inv = st.session_state.complete_inventory
        inv_data = st.session_state.inventory_data
        transfers = st.session_state.transfers_df
        branches = st.session_state.branches
        targets = st.session_state.branch_targets
        
        # Branch needs for dashboard
        needs = {}
        for b in branches:
            df = inv_data[b]
            target = targets.get(b, 8)
            total_needed = (target - df['Quantity']).clip(lower=0).sum()
            needs[b] = int(total_needed)
        
        # Create tabs
        tab_names = ["📊 Dashboard", "🚚 All Transfers", "📋 Zero Stock Anywhere"] + [f"🏪 {b}" for b in branches]
        tabs = st.tabs(tab_names)
        
        # Dashboard
        with tabs[0]:
            st.subheader("Branch‑wise Stock Needed")
            need_df = pd.DataFrame(list(needs.items()), columns=["Branch", "Units Needed"])
            need_df = need_df.sort_values("Units Needed", ascending=False)
            st.dataframe(need_df, use_container_width=True)
            if st.button("📄 Download Branch Needs PDF"):
                pdf = table_to_pdf(need_df, "Branch‑wise Stock Needed")
                if pdf:
                    st.download_button("Download PDF", pdf, "branch_needs.pdf")
            st.markdown("---")
            st.subheader("Branch Stock Summary")
            summary = []
            for b in branches:
                df = inv_data[b]
                tgt = targets.get(b, 8)
                total = int(df['Quantity'].sum())
                target_total = tgt * len(df)
                shortage = max(0, target_total - total)
                surplus = max(0, total - target_total)
                zero_skus = len(df[df['Quantity'] == 0])
                low_skus = len(df[(df['Quantity'] > 0) & (df['Quantity'] < tgt)])
                summary.append({
                    "Branch": b,
                    "Total Stock": total,
                    "Target Total": target_total,
                    "Shortage": shortage,
                    "Surplus": surplus,
                    "Zero SKUs": zero_skus,
                    "Low SKUs": low_skus
                })
            sum_df = pd.DataFrame(summary)
            st.dataframe(sum_df, use_container_width=True)
            if st.button("📄 Download Branch Summary PDF"):
                pdf = table_to_pdf(sum_df, "Branch Summary")
                if pdf:
                    st.download_button("Download PDF", pdf, "branch_summary.pdf")
        
        # All Transfers
        with tabs[1]:
            if not transfers.empty:
                disp = transfers[['From Branch', 'To Branch', 'Product', 'Size', 'Colour', 'Article', 'MRP', 'Transfer Qty']]
                st.dataframe(disp, use_container_width=True)
                if st.button("📄 Download All Transfers PDF"):
                    pdf = table_to_pdf(disp, "All Suggested Transfers", landscape=True)
                    if pdf:
                        st.download_button("Download PDF", pdf, "all_transfers.pdf")
            else:
                st.success("No transfers needed.")
        
        # Zero Stock Anywhere
        with tabs[2]:
            zero_all = []
            first = inv_data[branches[0]]
            if not first.empty:
                for sku in first['SKU'].unique():
                    total = 0
                    info = None
                    for b in branches:
                        row = inv_data[b][inv_data[b]['SKU'] == sku]
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
                if st.button("📄 Download Zero Stock Anywhere PDF"):
                    pdf = table_to_pdf(zero_df[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP']],
                                       "Products with Zero Stock Across All Branches")
                    if pdf:
                        st.download_button("Download PDF", pdf, "zero_anywhere.pdf")
            else:
                st.success("Every product has stock in at least one branch.")
        
        # Branch tabs
        for idx, branch in enumerate(branches):
            with tabs[idx+3]:
                config = {"name": branch, "target": targets.get(branch, 8)}
                branch_df = inv_data[branch].copy()
                if branch_df.empty:
                    st.info(f"No data for {branch}")
                    continue
                min_level = max(1, config["target"] // 2)
                
                # Metrics
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Total Stock", int(branch_df['Quantity'].sum()))
                c2.metric("SKUs", len(branch_df))
                c3.metric("Zero Stock", len(branch_df[branch_df['Quantity'] == 0]))
                c4.metric("Low Stock", len(branch_df[(branch_df['Quantity'] > 0) & (branch_df['Quantity'] < min_level)]))
                c5.metric("Surplus", len(branch_df[branch_df['Quantity'] > config["target"]]))
                
                # Zero Stock Table with search, multi‑select, delete
                st.subheader("Table 1: Zero Stock Items")
                zero = branch_df[branch_df['Quantity'] == 0].copy()
                if not zero.empty:
                    search = st.text_input(f"🔍 Search Article Number", key=f"search_{branch}")
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
                                st.session_state.inventory_data[branch] = new_df
                                st.session_state.transfers_df = calculate_transfers(st.session_state.inventory_data, targets)
                                st.success(f"Deleted {len(selected)} item(s) from {branch}")
                                st.rerun()
                            else:
                                st.warning("No items selected")
                    with col2:
                        if st.button(f"🔄 Reset Branch Data", key=f"reset_{branch}"):
                            st.session_state.inventory_data[branch] = complete_inv[branch].copy()
                            st.session_state.transfers_df = calculate_transfers(st.session_state.inventory_data, targets)
                            st.success(f"Reset {branch} to original")
                            st.rerun()
                    if st.button(f"📄 PDF - Zero Stock", key=f"zero_pdf_{branch}"):
                        pdf = table_to_pdf(zero[['Product','Brand','Size','Colour','Article','MRP']],
                                           f"{branch} - Zero Stock Items")
                        if pdf:
                            st.download_button("Download", pdf, f"{branch}_zero.pdf")
                else:
                    st.success("No zero stock items")
                
                # Low Stock Table (no delete)
                st.subheader("Table 2: Low Stock Items")
                low = branch_df[(branch_df['Quantity'] > 0) & (branch_df['Quantity'] < min_level)].copy()
                if not low.empty:
                    low_disp = low[['Product','Brand','Size','Colour','Article','MRP','Quantity']].copy()
                    low_disp.rename(columns={'Quantity':'Currently Available'}, inplace=True)
                    low_disp['Target'] = config["target"]
                    st.dataframe(low_disp, use_container_width=True)
                    if st.button(f"📄 PDF - Low Stock", key=f"low_pdf_{branch}"):
                        pdf = table_to_pdf(low_disp, f"{branch} - Low Stock Items")
                        if pdf:
                            st.download_button("Download", pdf, f"{branch}_low.pdf")
                else:
                    st.success("No low stock items")
                
                # Complete Inventory
                st.subheader("Table 3: Complete Inventory")
                full = branch_df[['Product','Brand','Size','Colour','Article','MRP','Quantity']].copy()
                full.rename(columns={'Quantity':'Currently Available'}, inplace=True)
                full['Status'] = full['Currently Available'].apply(
                    lambda x: 'Zero' if x==0 else ('Low' if x<min_level else ('Surplus' if x>config["target"] else 'OK'))
                )
                st.dataframe(full, use_container_width=True)
                if st.button(f"📄 PDF - Complete Inventory", key=f"full_pdf_{branch}"):
                    pdf = table_to_pdf(full, f"{branch} - Complete Inventory", landscape=True)
                    if pdf:
                        st.download_button("Download", pdf, f"{branch}_full.pdf")
                
                # Transfers involving this branch
                br_transfers = get_branch_transfers(transfers, branch)
                if not br_transfers.empty:
                    st.subheader("Suggested Transfers")
                    disp = br_transfers[['Product','Brand','Size','Colour','From Branch','To Branch','Transfer Qty']]
                    st.dataframe(disp, use_container_width=True)
                    if st.button(f"📄 PDF - Transfers", key=f"trans_pdf_{branch}"):
                        pdf = table_to_pdf(disp, f"{branch} - Transfer Orders", landscape=True)
                        if pdf:
                            st.download_button("Download", pdf, f"{branch}_transfers.pdf")

else:
    st.info("👈 Upload any inventory CSV file")
    st.markdown("""
    ## Universal Inventory Transfer System

    **Accepts any CSV** that contains a column with product descriptions in the format:  
    `Product - Colour - Size - Article - MRP`

    ### Features
    - Auto‑detects columns (branch, description, quantity) – **no manual mapping needed**
    - Branch‑wise stock needed analysis
    - Intelligent transfer suggestions (surplus → deficit, including warehouse)
    - **Zero stock table** – search by article, multi‑select delete (affects only that branch), reset
    - **PDF generation** for every table
    - Works with your original `SCHOOL STOCK.csv` (ragged) and the new structured format

    ### How to use
    1. Upload your CSV file.
    2. Set custom target stock levels per branch in the sidebar (optional).
    3. Explore the dashboard, transfers, and branch tabs.
    4. In any branch tab, **search, select and delete zero‑stock items** (changes are local to that branch).
    5. Download PDF reports as needed.
    """)
