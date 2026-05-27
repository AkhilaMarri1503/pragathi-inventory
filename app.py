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
st.markdown("**Works with any CSV file containing product descriptions with ' - ' separators**")

# ============================================
# BRANCH CONFIGURATION (fallback names)
# ============================================

# Known branch names for auto-detection
KNOWN_BRANCHES = [
    "POPULAR SHOE COMPANY", "PRAGATHI SHOES AMD 2", "PRAGATHI SHOES RAGOLU",
    "PRAGATHI SHOES BALAGA", "PRAGATHI SHOES AKP", "PRAGATHI SHOES",
    "POPULAR", "AMD 2", "RAGOLU", "BALAGA", "AKP", "WAREHOUSE"
]

# Target stock levels (user can modify)
BRANCH_TARGETS = {}

def clean_text(text):
    if pd.isna(text):
        return ""
    text = str(text)
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    text = text.replace('→', '->')
    return text.strip()

def get_brand(product):
    product_upper = product.upper()
    if "BOYS" in product_upper:
        return "Boys"
    elif "GIRLS" in product_upper:
        return "Girls"
    else:
        return "Unisex"

# ============================================
# UNIVERSAL CSV PARSER
# ============================================

def read_file_with_fallback(uploaded_file):
    raw_bytes = uploaded_file.getvalue()
    for encoding in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
        try:
            content = raw_bytes.decode(encoding)
            return content, encoding
        except:
            continue
    content = raw_bytes.decode('utf-8', errors='ignore')
    return content, 'utf-8 (with ignore)'

def parse_any_csv(content):
    """Parse any CSV, auto-detect columns, return list of product dicts."""
    # Try csv.reader (handles quoted commas)
    try:
        csv_reader = csv.reader(io.StringIO(content))
        rows = list(csv_reader)
        if rows:
            items = parse_rows_universal(rows)
            if items:
                return items, "csv.reader"
    except:
        pass
    
    # Fallback: simple split
    try:
        lines = content.splitlines()
        rows = [line.split(',') for line in lines]
        items = parse_rows_universal(rows)
        if items:
            return items, "simple split"
    except:
        pass
    
    return [], "none"

def parse_rows_universal(rows):
    """Auto-detect description, branch, quantity columns and parse all data rows."""
    if not rows:
        return []
    
    # Find the first row that contains " - " (data row, not header)
    first_data_idx = None
    for i, row in enumerate(rows):
        for cell in row:
            if " - " in cell:
                first_data_idx = i
                break
        if first_data_idx is not None:
            break
    
    if first_data_idx is None:
        return []
    
    # Use that row to detect column indices
    data_row = rows[first_data_idx]
    num_cols = len(data_row)
    
    # 1. Find description column: contains " - "
    desc_col = None
    for col in range(num_cols):
        if " - " in data_row[col]:
            desc_col = col
            break
    
    if desc_col is None:
        return []
    
    # 2. Find branch column: look for known branch names in the same row
    branch_col = None
    for col in range(num_cols):
        cell = data_row[col].strip()
        if any(branch in cell for branch in KNOWN_BRANCHES):
            branch_col = col
            break
    
    # Fallback: branch column is often immediately before description
    if branch_col is None and desc_col > 0:
        branch_col = desc_col - 1
    else:
        branch_col = 0  # fallback to first column
    
    # 3. Find quantity column: numeric, not the description column
    qty_col = None
    for col in range(num_cols):
        if col == desc_col:
            continue
        try:
            val = float(data_row[col])
            if val >= 0:
                qty_col = col
                break
        except:
            pass
    
    if qty_col is None:
        # Fallback: assume quantity is after description
        if desc_col + 1 < num_cols:
            qty_col = desc_col + 1
        else:
            qty_col = num_cols - 1
    
    # Now parse all rows from first_data_idx onward
    items = []
    for row in rows[first_data_idx:]:
        if len(row) <= max(desc_col, branch_col, qty_col):
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
        return None, None
    df_items = pd.DataFrame(all_items)
    df_items['SKU'] = df_items.apply(lambda x: f"{x['Product']}|{x['Colour']}|{x['Size']}|{x['Article']}|{x['MRP']}", axis=1)
    all_skus = df_items['SKU'].unique()
    # Get unique branch names from data
    unique_branches = df_items['Branch'].unique()
    # Create inventory dict for each branch
    complete_inventory = {}
    for branch in unique_branches:
        branch_data = df_items[df_items['Branch'] == branch]
        sku_dict = {row['SKU']: row['Quantity'] for _, row in branch_data.iterrows()}
        branch_records = []
        for sku in all_skus:
            sku_row = df_items[df_items['SKU'] == sku].iloc[0]
            quantity = sku_dict.get(sku, 0)
            branch_records.append({
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
        complete_inventory[branch] = pd.DataFrame(branch_records)
        # Initialize target stock level for this branch (default 8)
        if branch not in BRANCH_TARGETS:
            BRANCH_TARGETS[branch] = 8
    return complete_inventory, all_skus, unique_branches

# ============================================
# TRANSFER CALCULATION (dynamic branches)
# ============================================

def calculate_all_transfers(complete_inventory, branch_targets):
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
            sku_row = df[df['SKU'] == sku]
            if not sku_row.empty:
                quantity = sku_row['Quantity'].iloc[0]
                branch_stock[branch] = quantity
                if not sku_details:
                    sku_details = {
                        "Product": sku_row['Product'].iloc[0],
                        "Colour": sku_row['Colour'].iloc[0],
                        "Size": sku_row['Size'].iloc[0],
                        "Article": sku_row['Article'].iloc[0],
                        "MRP": sku_row['MRP'].iloc[0],
                        "Brand": sku_row['Brand'].iloc[0]
                    }
            else:
                branch_stock[branch] = 0
        if not sku_details:
            continue
        surplus_branches = []
        deficit_branches = []
        for branch, stock in branch_stock.items():
            target = branch_targets.get(branch, 8)
            if stock > target:
                surplus_branches.append({"branch": branch, "surplus": stock - target, "current": stock})
            elif stock < target:
                deficit_branches.append({"branch": branch, "needed": target - stock, "current": stock})
        for surplus in surplus_branches:
            remaining = surplus["surplus"]
            for deficit in deficit_branches[:]:
                if remaining <= 0:
                    break
                transfer_qty = min(remaining, deficit["needed"])
                if transfer_qty > 0:
                    all_transfers.append({
                        "SKU": sku,
                        "Product": sku_details['Product'],
                        "Colour": sku_details['Colour'],
                        "Size": sku_details['Size'],
                        "Article": sku_details['Article'],
                        "MRP": sku_details['MRP'],
                        "Brand": sku_details['Brand'],
                        "From Branch": surplus["branch"],
                        "From Current": surplus["current"],
                        "To Branch": deficit["branch"],
                        "To Current": deficit["current"],
                        "Transfer Qty": transfer_qty,
                        "Reason": f"Surplus from {surplus['branch']} to {deficit['branch']}"
                    })
                    remaining -= transfer_qty
                    deficit["needed"] -= transfer_qty
                    if deficit["needed"] <= 0:
                        deficit_branches.remove(deficit)
            surplus["surplus"] = remaining
    return pd.DataFrame(all_transfers) if all_transfers else pd.DataFrame()

def get_branch_transfers(transfers_df, branch_name):
    if transfers_df.empty:
        return pd.DataFrame()
    outgoing = transfers_df[transfers_df['From Branch'] == branch_name]
    incoming = transfers_df[transfers_df['To Branch'] == branch_name]
    return pd.concat([outgoing, incoming]) if not outgoing.empty or not incoming.empty else pd.DataFrame()

def generate_table_pdf(dataframe, title, columns=None, landscape=False):
    if dataframe.empty:
        return None
    pdf = FPDF()
    if landscape:
        pdf.add_page(orientation='L')
    else:
        pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(200, 10, clean_text(title), ln=True, align='C')
    pdf.set_font("Arial", size=8)
    pdf.ln(5)
    if columns is None:
        columns = dataframe.columns.tolist()
    columns = [c for c in columns if c in dataframe.columns]
    pdf.set_font("Arial", 'B', 8)
    col_widths = [max(20, min(50, len(str(c))*3)) for c in columns]
    total_width = sum(col_widths)
    if total_width > 260 and not landscape:
        pdf.add_page(orientation='L')
        col_widths = [max(20, min(60, len(str(c))*3)) for c in columns]
    for i, col in enumerate(columns):
        pdf.cell(col_widths[i], 8, clean_text(col), 1, 0, 'C')
    pdf.ln()
    pdf.set_font("Arial", size=7)
    for _, row in dataframe.iterrows():
        for i, col in enumerate(columns):
            cell_text = clean_text(str(row[col]))[:30]
            pdf.cell(col_widths[i], 7, cell_text, 1, 0, 'L')
        pdf.ln()
    return pdf.output(dest='S').encode('latin-1', errors='ignore')

# ============================================
# SESSION STATE MANAGEMENT
# ============================================

def reset_session():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# ============================================
# SIDEBAR
# ============================================

with st.sidebar:
    st.header("⚙️ Configuration")
    st.markdown("**Target Stock Levels**")
    st.info("Set desired stock per branch (adjust as needed)")
    # Targets will be populated after file load
    st.divider()
    uploaded_file = st.file_uploader("📁 Upload Inventory CSV (any format)", type=["csv"])
    if st.button("🔄 Reset All Data"):
        reset_session()

# ============================================
# MAIN APP
# ============================================

if uploaded_file:
    if "inventory_data" not in st.session_state or st.session_state.get("file_name") != uploaded_file.name:
        with st.spinner("Parsing inventory file (auto-detecting columns)..."):
            content, encoding = read_file_with_fallback(uploaded_file)
            items, method = parse_any_csv(content)
            if not items:
                st.error("Could not parse the file. Ensure it contains product descriptions with ' - ' (e.g., 'Product - Colour - Size - Article - MRP').")
                with st.expander("🔍 Debug: First 5 lines"):
                    lines = content.splitlines()[:5]
                    for i, line in enumerate(lines):
                        st.text(f"Line {i+1}: {line[:200]}")
                st.stop()
            complete_inventory, all_skus, branches = build_inventory(items)
            if complete_inventory is None:
                st.stop()
            st.session_state.complete_inventory = complete_inventory
            st.session_state.all_skus = all_skus
            st.session_state.branches = list(branches)
            st.session_state.inventory_data = complete_inventory.copy()
            st.session_state.file_name = uploaded_file.name
            # Initialize branch targets
            for branch in branches:
                if branch not in BRANCH_TARGETS:
                    BRANCH_TARGETS[branch] = 8
            st.session_state.branch_targets = BRANCH_TARGETS.copy()
            st.session_state.transfers_df = calculate_all_transfers(st.session_state.inventory_data, st.session_state.branch_targets)
            st.success(f"✅ Loaded {len(items)} product rows from {len(branches)} branches. Detection method: {method}")
            st.rerun()
    
    # Load from session
    complete_inventory = st.session_state.complete_inventory
    inventory_data = st.session_state.inventory_data
    transfers_df = st.session_state.transfers_df
    branches = st.session_state.branches
    branch_targets = st.session_state.branch_targets
    
    # Allow user to adjust targets per branch
    with st.sidebar:
        st.subheader("Branch Targets")
        for branch in branches:
            new_target = st.number_input(f"Target stock for {branch}", min_value=1, max_value=100, value=branch_targets[branch], key=f"target_{branch}")
            if new_target != branch_targets[branch]:
                branch_targets[branch] = new_target
                st.session_state.branch_targets = branch_targets
                st.session_state.transfers_df = calculate_all_transfers(st.session_state.inventory_data, branch_targets)
                st.rerun()
    
    # Compute branch needs
    branch_needs = {}
    for branch in branches:
        df = inventory_data[branch]
        target = branch_targets[branch]
        total_needed = (target - df['Quantity']).clip(lower=0).sum()
        branch_needs[branch] = int(total_needed)
    
    # Create tabs: Dashboard, All Transfers, Zero Stock Anywhere, then each branch
    tab_names = ["📊 Dashboard", "🚚 All Transfers", "📋 Zero Stock Anywhere"] + [f"🏪 {branch}" for branch in branches]
    tabs = st.tabs(tab_names)
    
    # Dashboard tab
    with tabs[0]:
        st.subheader("Branch-wise Stock Needed Analysis")
        need_df = pd.DataFrame(list(branch_needs.items()), columns=["Branch", "Total Units Needed"])
        need_df = need_df.sort_values("Total Units Needed", ascending=False)
        st.dataframe(need_df, use_container_width=True)
        if st.button("📄 Download Branch Needs PDF"):
            pdf_data = generate_table_pdf(need_df, "Branch-wise Stock Needed Report", columns=["Branch", "Total Units Needed"])
            if pdf_data:
                st.download_button("✅ Download PDF", pdf_data, "branch_needs.pdf")
        st.markdown("---")
        st.subheader("Branch Stock Summary")
        summary = []
        for branch in branches:
            df = inventory_data[branch]
            target = branch_targets[branch]
            total_stock = int(df['Quantity'].sum())
            target_total = target * len(df)
            shortage = max(0, target_total - total_stock)
            surplus = max(0, total_stock - target_total)
            zero_skus = len(df[df['Quantity'] == 0])
            low_skus = len(df[(df['Quantity'] > 0) & (df['Quantity'] < target)])
            summary.append({
                "Branch": branch,
                "Total Stock": total_stock,
                "Target Total": target_total,
                "Shortage": shortage,
                "Surplus": surplus,
                "Zero SKUs": zero_skus,
                "Low SKUs": low_skus
            })
        summary_df = pd.DataFrame(summary)
        st.dataframe(summary_df, use_container_width=True)
        if st.button("📄 Download Branch Summary PDF"):
            pdf_data = generate_table_pdf(summary_df, "Branch Summary Report")
            if pdf_data:
                st.download_button("✅ Download PDF", pdf_data, "branch_summary.pdf")
    
    # All Transfers tab
    with tabs[1]:
        if not transfers_df.empty:
            display_transfers = transfers_df[['From Branch', 'To Branch', 'Product', 'Size', 'Brand', 'Colour', 'Article', 'MRP', 'Transfer Qty']]
            st.dataframe(display_transfers, use_container_width=True)
            if st.button("📄 Download All Transfers PDF"):
                pdf_data = generate_table_pdf(display_transfers, "All Suggested Transfers", landscape=True)
                if pdf_data:
                    st.download_button("✅ Download PDF", pdf_data, "all_transfers.pdf")
        else:
            st.success("No transfers needed.")
    
    # Zero Stock Anywhere tab
    with tabs[2]:
        zero_across_all = []
        if branches:
            first_branch_df = inventory_data[branches[0]]
            if not first_branch_df.empty:
                for sku in first_branch_df['SKU'].unique():
                    total = 0
                    sku_info = None
                    for branch in branches:
                        df = inventory_data[branch]
                        row = df[df['SKU'] == sku]
                        if not row.empty:
                            total += row['Quantity'].iloc[0]
                            if sku_info is None:
                                sku_info = {
                                    "Product": row['Product'].iloc[0],
                                    "Colour": row['Colour'].iloc[0],
                                    "Size": row['Size'].iloc[0],
                                    "Brand": row['Brand'].iloc[0],
                                    "Article": row['Article'].iloc[0],
                                    "MRP": row['MRP'].iloc[0]
                                }
                    if total == 0 and sku_info:
                        zero_across_all.append(sku_info)
        zero_df = pd.DataFrame(zero_across_all)
        if not zero_df.empty:
            st.error(f"{len(zero_df)} products have zero stock in all branches")
            st.dataframe(zero_df[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP']], use_container_width=True)
            if st.button("📄 Download Zero Stock Anywhere PDF"):
                pdf_data = generate_table_pdf(zero_df[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP']], "Products with Zero Stock Across All Branches")
                if pdf_data:
                    st.download_button("✅ Download PDF", pdf_data, "zero_stock_anywhere.pdf")
        else:
            st.success("All products have stock in at least one branch.")
    
    # Branch-specific tabs
    for idx, branch in enumerate(branches):
        with tabs[idx + 3]:
            branch_df = inventory_data[branch].copy()
            if branch_df.empty:
                st.info(f"No data for {branch}")
                continue
            target = branch_targets[branch]
            min_level = max(1, target // 2)  # low stock threshold = half of target
            
            # Metrics
            col1, col2, col3, col4, col5 = st.columns(5)
            total_stock = int(branch_df['Quantity'].sum())
            sku_count = len(branch_df)
            zero_count = len(branch_df[branch_df['Quantity'] == 0])
            low_count = len(branch_df[(branch_df['Quantity'] > 0) & (branch_df['Quantity'] < min_level)])
            surplus_count = len(branch_df[branch_df['Quantity'] > target])
            col1.metric("Total Stock", total_stock)
            col2.metric("Total SKUs", sku_count)
            col3.metric("Zero Stock", zero_count)
            col4.metric("Low Stock", low_count)
            col5.metric("Surplus", surplus_count)
            
            # Zero Stock Table
            st.subheader("Zero Stock Items")
            zero_stock = branch_df[branch_df['Quantity'] == 0].copy()
            if not zero_stock.empty:
                search = st.text_input(f"🔍 Search Article Number", key=f"search_{branch}")
                if search:
                    zero_stock = zero_stock[zero_stock['Article'].str.contains(search, case=False, na=False)]
                display_zero = zero_stock[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP']].reset_index(drop=True)
                display_zero.insert(0, "Select", False)
                edited = st.data_editor(
                    display_zero,
                    column_config={"Select": st.column_config.CheckboxColumn("Select", default=False)},
                    disabled=['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP'],
                    hide_index=True,
                    key=f"editor_{branch}"
                )
                selected = edited[edited['Select'] == True]['Article'].tolist()
                col_del, col_reset = st.columns(2)
                with col_del:
                    if st.button(f"🗑️ Delete Selected", key=f"del_{branch}"):
                        if selected:
                            new_df = branch_df[~branch_df['Article'].isin(selected)]
                            st.session_state.inventory_data[branch] = new_df
                            st.session_state.transfers_df = calculate_all_transfers(st.session_state.inventory_data, branch_targets)
                            st.success(f"Deleted {len(selected)} item(s) from {branch}")
                            st.rerun()
                        else:
                            st.warning("No items selected")
                with col_reset:
                    if st.button(f"🔄 Reset Branch Data", key=f"reset_{branch}"):
                        st.session_state.inventory_data[branch] = complete_inventory[branch].copy()
                        st.session_state.transfers_df = calculate_all_transfers(st.session_state.inventory_data, branch_targets)
                        st.success(f"Reset {branch} to original data")
                        st.rerun()
                if st.button(f"📄 PDF - Zero Stock", key=f"zero_pdf_{branch}"):
                    pdf_data = generate_table_pdf(zero_stock[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP']], f"{branch} - Zero Stock Items")
                    if pdf_data:
                        st.download_button("✅ Download", pdf_data, f"{branch}_zero_stock.pdf")
            else:
                st.success("No zero stock items")
            
            # Low Stock Table
            st.subheader("Low Stock Items")
            low_stock = branch_df[(branch_df['Quantity'] > 0) & (branch_df['Quantity'] < min_level)].copy()
            if not low_stock.empty:
                low_display = low_stock[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP', 'Quantity']].copy()
                low_display.rename(columns={'Quantity': 'Currently Available'}, inplace=True)
                low_display['Target'] = target
                st.dataframe(low_display, use_container_width=True)
                if st.button(f"📄 PDF - Low Stock", key=f"low_pdf_{branch}"):
                    pdf_data = generate_table_pdf(low_display, f"{branch} - Low Stock Items",
                                                 columns=['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP', 'Currently Available', 'Target'])
                    if pdf_data:
                        st.download_button("✅ Download", pdf_data, f"{branch}_low_stock.pdf")
            else:
                st.success("No low stock items")
            
            # Complete Inventory
            st.subheader("Complete Inventory")
            full_display = branch_df[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP', 'Quantity']].copy()
            full_display.rename(columns={'Quantity': 'Currently Available'}, inplace=True)
            full_display['Status'] = full_display['Currently Available'].apply(
                lambda x: 'Zero' if x==0 else ('Low' if x<min_level else ('Surplus' if x>target else 'OK'))
            )
            st.dataframe(full_display, use_container_width=True)
            if st.button(f"📄 PDF - Complete Inventory", key=f"full_pdf_{branch}"):
                pdf_data = generate_table_pdf(full_display, f"{branch} - Complete Inventory", landscape=True)
                if pdf_data:
                    st.download_button("✅ Download", pdf_data, f"{branch}_complete_inventory.pdf")
            
            # Transfers for this branch
            branch_transfers = get_branch_transfers(transfers_df, branch)
            if not branch_transfers.empty:
                st.subheader("Suggested Transfers (Send/Receive)")
                transfer_display = branch_transfers[['Product', 'Brand', 'Size', 'Colour', 'From Branch', 'To Branch', 'Transfer Qty']]
                st.dataframe(transfer_display, use_container_width=True)
                if st.button(f"📄 PDF - Transfers", key=f"trans_pdf_{branch}"):
                    pdf_data = generate_table_pdf(transfer_display, f"{branch} - Transfer Orders", landscape=True)
                    if pdf_data:
                        st.download_button("✅ Download", pdf_data, f"{branch}_transfers.pdf")

else:
    st.info("👈 Upload any inventory CSV file")
    st.markdown("""
    ## Universal Inventory Transfer System
    
    ### Works with ANY CSV that contains:
    - A column with product descriptions in the format: `Product - Colour - Size - Article - MRP`
    - A column with branch/store names
    - A column with quantities (numeric)
    
    ### Features:
    - **Auto-detects** columns (no manual mapping needed)
    - **Handles** ragged rows, different encodings, quoted fields
    - **Branch-wise** zero‑stock deletion (affects only that branch)
    - **PDF reports** for every table
    - **Dynamic target levels** per branch (adjust in sidebar)
    """)
