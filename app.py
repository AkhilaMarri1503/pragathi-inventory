import streamlit as st
import pandas as pd
import numpy as np
from fpdf import FPDF
from datetime import datetime
import re

st.set_page_config(page_title="Pragathi Shoes - Complete Transfer System", layout="wide")

st.title("👞 Pragathi Shoes - Complete Stock Transfer System")
st.markdown("**Intelligent surplus redistribution across all branches including warehouse**")

# ============================================
# BRANCH CONFIGURATION
# ============================================

BRANCHES = {
    "POPULAR SHOE COMPANY": {"target": 12, "min": 6, "name": "Popular Store", "order": 1},
    "PRAGATHI SHOES AMD 2": {"target": 8, "min": 4, "name": "AMD 2 Store", "order": 2},
    "PRAGATHI SHOES RAGOLU": {"target": 8, "min": 4, "name": "Ragolu Store", "order": 3},
    "PRAGATHI SHOES BALAGA": {"target": 8, "min": 4, "name": "Balaga Store", "order": 4},
    "PRAGATHI SHOES AKP": {"target": 8, "min": 4, "name": "AKP Store", "order": 5},
    "PRAGATHI SHOES": {"target": 20, "min": 10, "name": "Central Warehouse", "order": 6}
}

BRANCH_ORDER = ["POPULAR SHOE COMPANY", "PRAGATHI SHOES AMD 2", "PRAGATHI SHOES RAGOLU", 
                "PRAGATHI SHOES BALAGA", "PRAGATHI SHOES AKP", "PRAGATHI SHOES"]

def clean_text(text):
    if pd.isna(text):
        return ""
    text = str(text)
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    text = text.replace('→', '->')
    return text.strip()

# Helper to extract brand from product name
def get_brand(product):
    product_upper = product.upper()
    if "BOYS" in product_upper:
        return "Pragathi Boys"
    elif "GIRLS" in product_upper:
        return "Pragathi Girls"
    else:
        return "Pragathi"

# ============================================
# DATA PROCESSING
# ============================================

def process_inventory_file(uploaded_file):
    df = pd.read_csv(uploaded_file, header=None)
    all_items = []
    for _, row in df.iterrows():
        try:
            branch = str(row[15]).strip()
            desc = str(row[16]).strip()
            qty = float(row[17]) if row[17] else 0
            if " - " in desc and len(desc) > 10:
                parts = desc.split(" - ")
                if len(parts) >= 5:
                    all_items.append({
                        "Branch": branch,
                        "Product": parts[0].strip(),
                        "Colour": parts[1].strip(),
                        "Size": parts[2].strip(),
                        "Article": parts[3].strip(),
                        "MRP": parts[4].strip(),
                        "Quantity": qty
                    })
        except:
            continue
    df_items = pd.DataFrame(all_items)
    if df_items.empty:
        return None, None
    df_items['SKU'] = df_items.apply(lambda x: f"{x['Product']}|{x['Colour']}|{x['Size']}|{x['Article']}|{x['MRP']}", axis=1)
    all_skus = df_items['SKU'].unique()
    complete_inventory = {}
    for branch in BRANCHES.keys():
        branch_data = df_items[df_items['Branch'] == branch] if branch in df_items['Branch'].values else pd.DataFrame()
        sku_dict = {}
        if not branch_data.empty:
            for _, row in branch_data.iterrows():
                sku_dict[row['SKU']] = row['Quantity']
        branch_records = []
        for sku in all_skus:
            sku_row = df_items[df_items['SKU'] == sku].iloc[0] if not df_items[df_items['SKU'] == sku].empty else None
            if sku_row is not None:
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
                    "Brand": get_brand(sku_row['Product'])   # added brand
                })
        complete_inventory[branch] = pd.DataFrame(branch_records)
    return complete_inventory, all_skus

def calculate_all_transfers(complete_inventory, branches_config):
    all_transfers = []
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
            if branch != "PRAGATHI SHOES":
                target = branches_config[branch]["target"]
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
# SIDEBAR
# ============================================

with st.sidebar:
    st.header("⚙️ Branch Configuration")
    for branch in BRANCH_ORDER:
        if branch != "PRAGATHI SHOES":
            default = BRANCHES[branch]["target"]
            BRANCHES[branch]["target"] = st.number_input(
                f"{BRANCHES[branch]['name']}", value=default, min_value=1, max_value=50, key=f"target_{branch}"
            )
    st.subheader("Warehouse Configuration")
    BRANCHES["PRAGATHI SHOES"]["target"] = st.number_input("Central Warehouse", value=20, min_value=5, max_value=100)
    st.divider()
    uploaded_file = st.file_uploader("📁 Upload SCHOOL STOCK.csv", type=["csv"])

# ============================================
# MAIN APP
# ============================================

if uploaded_file:
    with st.spinner("Analyzing inventory across all branches..."):
        complete_inventory, all_skus = process_inventory_file(uploaded_file)
        if complete_inventory is None:
            st.error("Could not parse file. Check format.")
            st.stop()
        transfers_df = calculate_all_transfers(complete_inventory, BRANCHES)
        
        branch_needs = {}
        for branch in BRANCH_ORDER:
            if branch == "PRAGATHI SHOES":
                continue
            df = complete_inventory[branch]
            target = BRANCHES[branch]["target"]
            total_needed = (target - df['Quantity']).clip(lower=0).sum()
            branch_needs[BRANCHES[branch]["name"]] = int(total_needed)
        
        tab_names = ["📊 Dashboard", "🚚 All Transfers", "📋 Zero Stock Anywhere"] + [f"🏪 {BRANCHES[b]['name']}" for b in BRANCH_ORDER]
        tabs = st.tabs(tab_names)
        
        # Dashboard
        with tabs[0]:
            st.subheader("Branch-wise Stock Needed Analysis")
            need_df = pd.DataFrame(list(branch_needs.items()), columns=["Branch", "Total Units Needed"])
            need_df = need_df.sort_values("Total Units Needed", ascending=False)
            st.dataframe(need_df, use_container_width=True)
            if st.button("📄 Download Branch Needs PDF", key="needs_pdf"):
                pdf_data = generate_table_pdf(need_df, "Branch-wise Stock Needed Report", columns=["Branch", "Total Units Needed"])
                if pdf_data:
                    st.download_button("✅ Download PDF", pdf_data, "branch_needs.pdf")
            
            st.markdown("---")
            st.subheader("Branch Stock Summary")
            summary = []
            for branch in BRANCH_ORDER:
                if branch == "PRAGATHI SHOES":
                    continue
                df = complete_inventory[branch]
                config = BRANCHES[branch]
                total_stock = int(df['Quantity'].sum())
                target_total = config['target'] * len(df)
                shortage = max(0, target_total - total_stock)
                surplus = max(0, total_stock - target_total)
                zero_skus = len(df[df['Quantity'] == 0])
                low_skus = len(df[(df['Quantity'] > 0) & (df['Quantity'] < config['min'])])
                summary.append({
                    "Branch": config['name'],
                    "Total Stock": total_stock,
                    "Target": target_total,
                    "Shortage": shortage,
                    "Surplus": surplus,
                    "Zero SKUs": zero_skus,
                    "Low SKUs": low_skus
                })
            summary_df = pd.DataFrame(summary)
            st.dataframe(summary_df, use_container_width=True)
            if st.button("📄 Download Branch Summary PDF", key="summary_pdf"):
                pdf_data = generate_table_pdf(summary_df, "Branch Summary Report")
                if pdf_data:
                    st.download_button("✅ Download PDF", pdf_data, "branch_summary.pdf")
        
        # All Transfers
        with tabs[1]:
            if not transfers_df.empty:
                display_transfers = transfers_df[['From Branch', 'To Branch', 'Product', 'Size', 'Brand', 'Colour', 'Article', 'MRP', 'Transfer Qty']]
                st.dataframe(display_transfers, use_container_width=True)
                if st.button("📄 Download All Transfers PDF", key="all_trans_pdf"):
                    pdf_data = generate_table_pdf(display_transfers, "All Suggested Transfers", landscape=True)
                    if pdf_data:
                        st.download_button("✅ Download PDF", pdf_data, "all_transfers.pdf")
            else:
                st.success("No transfers needed.")
        
        # Zero Stock Anywhere
        with tabs[2]:
            zero_across_all = []
            first_branch_df = complete_inventory[BRANCH_ORDER[0]]
            if not first_branch_df.empty:
                for sku in first_branch_df['SKU'].unique():
                    total = 0
                    sku_info = None
                    for branch in BRANCH_ORDER:
                        df = complete_inventory[branch]
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
                if st.button("📄 Download Zero Stock Anywhere PDF", key="zero_all_pdf"):
                    pdf_data = generate_table_pdf(zero_df[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP']], "Products with Zero Stock Across All Branches")
                    if pdf_data:
                        st.download_button("✅ Download PDF", pdf_data, "zero_stock_anywhere.pdf")
            else:
                st.success("All products have stock in at least one branch.")
        
        # Branch-specific tabs
        for idx, branch in enumerate(BRANCH_ORDER):
            with tabs[idx + 3]:
                config = BRANCHES[branch]
                branch_df = complete_inventory[branch]
                if branch_df.empty:
                    st.info(f"No data for {config['name']}")
                    continue
                
                # Metrics
                col1, col2, col3, col4, col5 = st.columns(5)
                total_stock = int(branch_df['Quantity'].sum())
                sku_count = len(branch_df)
                zero_count = len(branch_df[branch_df['Quantity'] == 0])
                low_count = len(branch_df[(branch_df['Quantity'] > 0) & (branch_df['Quantity'] < config['min'])])
                surplus_count = len(branch_df[branch_df['Quantity'] > config['target']])
                col1.metric("Total Stock", total_stock)
                col2.metric("Total SKUs", sku_count)
                col3.metric("Zero Stock", zero_count)
                col4.metric("Low Stock", low_count)
                col5.metric("Surplus", surplus_count)
                
                # Table 1: Zero Stock Items (showing Brand, Size, etc.)
                st.subheader("Table 1: Zero Stock Items")
                zero_stock = branch_df[branch_df['Quantity'] == 0]
                if not zero_stock.empty:
                    zero_display = zero_stock[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP']]
                    st.dataframe(zero_display, use_container_width=True)
                    if st.button(f"📄 PDF - Zero Stock", key=f"zero_{branch}"):
                        pdf_data = generate_table_pdf(zero_display, f"{config['name']} - Zero Stock Items")
                        if pdf_data:
                            st.download_button("✅ Download", pdf_data, f"{branch}_zero_stock.pdf")
                else:
                    st.success("No zero stock items")
                
                # Table 2: Low Stock Items (remove Quantity column, remove min required, show Currently Available)
                st.subheader("Table 2: Low Stock Items")
                low_stock = branch_df[(branch_df['Quantity'] > 0) & (branch_df['Quantity'] < config['min'])]
                if not low_stock.empty:
                    low_display = low_stock[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP', 'Quantity']].copy()
                    low_display.rename(columns={'Quantity': 'Currently Available'}, inplace=True)
                    # Remove any "min required" column if exists (we never added it)
                    st.dataframe(low_display, use_container_width=True)
                    if st.button(f"📄 PDF - Low Stock", key=f"low_{branch}"):
                        pdf_data = generate_table_pdf(low_display, f"{config['name']} - Low Stock Items", 
                                                     columns=['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP', 'Currently Available'])
                        if pdf_data:
                            st.download_button("✅ Download", pdf_data, f"{branch}_low_stock.pdf")
                else:
                    st.success("No low stock items")
                
                # Table 3: Complete Inventory (rename 'Quantity' to 'Currently Available')
                st.subheader("Table 3: Complete Inventory")
                full_display = branch_df[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP', 'Quantity']].copy()
                full_display.rename(columns={'Quantity': 'Currently Available'}, inplace=True)
                full_display['Status'] = full_display['Currently Available'].apply(
                    lambda x: 'Zero' if x==0 else ('Low' if x<config['min'] else ('Surplus' if x>config['target'] else 'OK'))
                )
                st.dataframe(full_display, use_container_width=True)
                if st.button(f"📄 PDF - Complete Inventory", key=f"full_{branch}"):
                    pdf_data = generate_table_pdf(full_display, f"{config['name']} - Complete Inventory", landscape=True)
                    if pdf_data:
                        st.download_button("✅ Download", pdf_data, f"{branch}_complete_inventory.pdf")
                
                # Transfers for this branch
                branch_transfers = get_branch_transfers(transfers_df, branch)
                if not branch_transfers.empty:
                    st.subheader("Suggested Transfers (Send/Receive)")
                    transfer_display = branch_transfers[['Product', 'Brand', 'Size', 'Colour', 'From Branch', 'To Branch', 'Transfer Qty']]
                    st.dataframe(transfer_display, use_container_width=True)
                    if st.button(f"📄 PDF - Transfers", key=f"trans_{branch}"):
                        pdf_data = generate_table_pdf(transfer_display, f"{config['name']} - Transfer Orders", landscape=True)
                        if pdf_data:
                            st.download_button("✅ Download", pdf_data, f"{branch}_transfers.pdf")

else:
    st.info("👈 Upload your SCHOOL STOCK.csv file using the sidebar")
    st.markdown("""
    ## Features:
    - **Branch-wise Stock Needed Analysis** in Dashboard
    - **PDF Generation** for every table
    - **Brand column** added (next to Size)
    - **"Currently Available"** instead of "Quantity"
    - Low stock items table simplified (no min required, no extra quantity column)
    """)
