import streamlit as st
import pandas as pd
import numpy as np
from fpdf import FPDF
from datetime import datetime
import re
import io

st.set_page_config(page_title="Universal Inventory Transfer System", layout="wide")

st.title("📦 Universal Inventory Transfer System")
st.markdown("**Works with any CSV file containing product descriptions with ' - ' separators**")

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
    product_upper = product.upper()
    if "BOYS" in product_upper:
        return "Boys"
    elif "GIRLS" in product_upper:
        return "Girls"
    else:
        return "Unisex"

# ============================================
# LINE‑BASED PARSER (BYPASSES CSV ISSUES)
# ============================================

def parse_raw_lines(content):
    """Parse raw file content line by line, looking for ' - '."""
    lines = content.splitlines()
    items = []
    
    # First pass: find the first line that contains " - "
    data_start = None
    for i, line in enumerate(lines):
        if " - " in line:
            data_start = i
            break
    
    if data_start is None:
        return items, None, None, None
    
    # Now, try to detect column indices by analyzing the first data line
    sample_line = lines[data_start]
    # Split by comma (simple split, but preserve quoted parts)
    # We'll use a simple regex to split on commas that are not inside quotes
    fields = re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', sample_line)
    fields = [f.strip().strip('"') for f in fields]
    
    # Find description column (contains " - ")
    desc_idx = None
    for i, f in enumerate(fields):
        if " - " in f:
            desc_idx = i
            break
    
    if desc_idx is None:
        return items, None, None, None
    
    # Find branch column: look for known branch names
    branch_idx = None
    for i, f in enumerate(fields):
        if any(branch in f for branch in KNOWN_BRANCHES):
            branch_idx = i
            break
    if branch_idx is None and desc_idx > 0:
        branch_idx = desc_idx - 1  # often before description
    else:
        branch_idx = 0
    
    # Find quantity column: look for a numeric field (not the description)
    qty_idx = None
    for i, f in enumerate(fields):
        if i == desc_idx:
            continue
        try:
            val = float(f)
            if val >= 0:
                qty_idx = i
                break
        except:
            pass
    if qty_idx is None and desc_idx + 1 < len(fields):
        qty_idx = desc_idx + 1
    else:
        qty_idx = len(fields) - 1
    
    # Now parse all lines from data_start onward
    for line in lines[data_start:]:
        if not line.strip():
            continue
        # Split line respecting quotes
        parts = re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', line)
        parts = [p.strip().strip('"') for p in parts]
        if len(parts) <= max(desc_idx, branch_idx, qty_idx):
            continue
        desc = parts[desc_idx]
        if " - " not in desc:
            continue
        branch = parts[branch_idx]
        try:
            qty = float(parts[qty_idx])
        except:
            qty = 0
        if qty < 0:
            qty = 0
        parts_desc = desc.split(" - ")
        if len(parts_desc) >= 5:
            items.append({
                "Branch": branch,
                "Product": parts_desc[0].strip(),
                "Colour": parts_desc[1].strip(),
                "Size": parts_desc[2].strip(),
                "Article": parts_desc[3].strip(),
                "MRP": parts_desc[4].strip(),
                "Quantity": qty
            })
    
    return items, desc_idx, branch_idx, qty_idx

def read_file_content(uploaded_file):
    raw_bytes = uploaded_file.getvalue()
    for encoding in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
        try:
            content = raw_bytes.decode(encoding)
            return content, encoding
        except:
            continue
    content = raw_bytes.decode('utf-8', errors='ignore')
    return content, 'utf-8 (with ignore)'

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
    return complete_inventory, all_skus, list(unique_branches)

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
# SESSION STATE
# ============================================

if "inventory_loaded" not in st.session_state:
    st.session_state.inventory_loaded = False
    st.session_state.complete_inventory = {}
    st.session_state.inventory_data = {}
    st.session_state.branches = []
    st.session_state.branch_targets = {}
    st.session_state.transfers_df = pd.DataFrame()
    st.session_state.file_name = None
    st.session_state.manual_mode = False
    st.session_state.manual_desc = 0
    st.session_state.manual_branch = 0
    st.session_state.manual_qty = 0

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
            new_val = st.number_input(f"Target for {branch}", min_value=1, max_value=100, value=current, key=f"target_{branch}")
            if new_val != current:
                st.session_state.branch_targets[branch] = new_val
                st.session_state.transfers_df = calculate_all_transfers(st.session_state.inventory_data, st.session_state.branch_targets)
                st.rerun()
    
    if st.button("🔄 Reset All Data"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# ============================================
# MAIN APP
# ============================================

if uploaded_file:
    # Check if file changed
    if st.session_state.file_name != uploaded_file.name or not st.session_state.inventory_loaded:
        with st.spinner("Parsing inventory file..."):
            content, encoding = read_file_content(uploaded_file)
            items, auto_desc, auto_branch, auto_qty = parse_raw_lines(content)
            
            if not items:
                # Auto-detection failed, show manual column selection
                st.warning("Auto-detection failed. Please manually select the correct columns.")
                st.session_state.manual_mode = True
                st.session_state.raw_content = content
                # Show a preview of the first few data lines
                lines = content.splitlines()
                # Find first line with " - "
                data_start = None
                for i, line in enumerate(lines):
                    if " - " in line:
                        data_start = i
                        break
                if data_start is not None:
                    sample_lines = lines[data_start:data_start+3]
                    st.subheader("Preview of product data rows (first 3):")
                    for i, line in enumerate(sample_lines):
                        st.code(line, language='text')
                else:
                    st.error("No line contains ' - '. Please check the file format.")
                    st.stop()
                
                # Let user set column indices
                st.subheader("Column Mapping")
                # We need to parse one sample line to show fields
                sample_line = lines[data_start] if data_start is not None else lines[0]
                fields = re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', sample_line)
                fields = [f.strip().strip('"') for f in fields]
                st.write(f"Found {len(fields)} fields in a sample row:")
                for i, f in enumerate(fields):
                    st.write(f"  {i}: {f[:50]}")
                
                desc_idx = st.number_input("Description column index (contains ' - ')", min_value=0, max_value=len(fields)-1, value=auto_desc if auto_desc is not None else 0)
                branch_idx = st.number_input("Branch column index", min_value=0, max_value=len(fields)-1, value=auto_branch if auto_branch is not None else 0)
                qty_idx = st.number_input("Quantity column index (numeric)", min_value=0, max_value=len(fields)-1, value=auto_qty if auto_qty is not None else 1)
                
                if st.button("✅ Parse with these columns"):
                    # Re-parse using manual indices
                    lines = content.splitlines()
                    new_items = []
                    for line in lines:
                        if " - " not in line:
                            continue
                        parts = re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', line)
                        parts = [p.strip().strip('"') for p in parts]
                        if len(parts) <= max(desc_idx, branch_idx, qty_idx):
                            continue
                        desc = parts[desc_idx]
                        if " - " not in desc:
                            continue
                        branch = parts[branch_idx]
                        try:
                            qty = float(parts[qty_idx])
                        except:
                            qty = 0
                        if qty < 0:
                            qty = 0
                        parts_desc = desc.split(" - ")
                        if len(parts_desc) >= 5:
                            new_items.append({
                                "Branch": branch,
                                "Product": parts_desc[0].strip(),
                                "Colour": parts_desc[1].strip(),
                                "Size": parts_desc[2].strip(),
                                "Article": parts_desc[3].strip(),
                                "MRP": parts_desc[4].strip(),
                                "Quantity": qty
                            })
                    items = new_items
                    if not items:
                        st.error("Still no valid items. Please check column indices.")
                        st.stop()
                    st.success(f"Parsed {len(items)} items with manual mapping.")
                    st.session_state.manual_mode = False
                    # Proceed to build inventory
                    complete_inventory, all_skus, branches = build_inventory(items)
                    if complete_inventory is None:
                        st.stop()
                    branch_targets = {branch: 8 for branch in branches}
                    transfers_df = calculate_all_transfers(complete_inventory, branch_targets)
                    st.session_state.complete_inventory = complete_inventory
                    st.session_state.inventory_data = complete_inventory.copy()
                    st.session_state.branches = branches
                    st.session_state.branch_targets = branch_targets
                    st.session_state.transfers_df = transfers_df
                    st.session_state.file_name = uploaded_file.name
                    st.session_state.inventory_loaded = True
                    st.rerun()
                st.stop()
            else:
                # Auto-detection succeeded
                st.session_state.manual_mode = False
                complete_inventory, all_skus, branches = build_inventory(items)
                if complete_inventory is None:
                    st.stop()
                branch_targets = {branch: 8 for branch in branches}
                transfers_df = calculate_all_transfers(complete_inventory, branch_targets)
                st.session_state.complete_inventory = complete_inventory
                st.session_state.inventory_data = complete_inventory.copy()
                st.session_state.branches = branches
                st.session_state.branch_targets = branch_targets
                st.session_state.transfers_df = transfers_df
                st.session_state.file_name = uploaded_file.name
                st.session_state.inventory_loaded = True
                st.success(f"✅ Loaded {len(items)} product rows from {len(branches)} branches. Encoding: {encoding}")
                st.rerun()
    
    # Display content if loaded
    if st.session_state.inventory_loaded and st.session_state.branches:
        complete_inventory = st.session_state.complete_inventory
        inventory_data = st.session_state.inventory_data
        transfers_df = st.session_state.transfers_df
        branches = st.session_state.branches
        branch_targets = st.session_state.branch_targets
        
        # Compute branch needs
        branch_needs = {}
        for branch in branches:
            df = inventory_data[branch]
            target = branch_targets[branch]
            total_needed = (target - df['Quantity']).clip(lower=0).sum()
            branch_needs[branch] = int(total_needed)
        
        tab_names = ["📊 Dashboard", "🚚 All Transfers", "📋 Zero Stock Anywhere"] + [f"🏪 {branch}" for branch in branches]
        tabs = st.tabs(tab_names)
        
        # Dashboard
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
        
        # All Transfers
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
        
        # Zero Stock Anywhere
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
                min_level = max(1, target // 2)
                
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
    - **Auto-detects** columns using raw line scanning (bypasses CSV parsing issues)
    - **Manual column mapping** if auto-detection fails
    - **Handles ragged rows, different encodings, quoted fields**
    - **Branch-wise** zero‑stock deletion (affects only that branch)
    - **PDF reports** for every table
    - **Dynamic target levels** per branch (adjust in sidebar)
    """)
