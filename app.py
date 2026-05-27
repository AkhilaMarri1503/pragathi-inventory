import streamlit as st
import pandas as pd
import numpy as np
from fpdf import FPDF
from datetime import datetime
import re
import io

st.set_page_config(page_title="Pragathi Shoes - Complete Transfer System", layout="wide")
st.title("👞 Pragathi Shoes – Complete Stock Transfer System")
st.markdown("**Warehouse is last resort; retail‑to‑retail transfers prioritised**")

# ============================================
# HELPER FUNCTIONS
# ============================================

def clean_text(text):
    if pd.isna(text):
        return ""
    text = str(text)
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    return text.strip()

def table_to_excel(df):
    """Convert dataframe to Excel bytes for download."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Data')
    return output.getvalue()

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
# EXCEL PARSER
# ============================================

def parse_excel(uploaded_file):
    df_raw = pd.read_excel(uploaded_file, sheet_name='Sheet1', header=None)
    
    header_row_idx = None
    for i in range(len(df_raw)):
        if df_raw.iloc[i, 0] == 'Branch':
            header_row_idx = i
            break
    
    if header_row_idx is None:
        st.error("Could not find header row (expected 'Branch' in column A).")
        return []
    
    header_vals = df_raw.iloc[header_row_idx].tolist()
    col_map = {}
    for idx, val in enumerate(header_vals):
        val_str = str(val).strip().lower()
        if val_str == 'branch':
            col_map['branch'] = idx
        elif val_str == 'product':
            col_map['product'] = idx
        elif val_str == 'brand':
            col_map['brand'] = idx
        elif val_str == 'colour':
            col_map['colour'] = idx
        elif val_str == 'size':
            col_map['size'] = idx
        elif val_str == 'artical':
            col_map['article'] = idx
        elif val_str == 'mrp':
            col_map['mrp'] = idx
        elif val_str == 'clqty':
            col_map['qty'] = idx
    
    required = ['branch', 'product', 'brand', 'colour', 'size', 'article', 'mrp', 'qty']
    missing = [r for r in required if r not in col_map]
    if missing:
        st.error(f"Missing columns in header: {missing}")
        return []
    
    items = []
    for i in range(header_row_idx + 1, len(df_raw)):
        row = df_raw.iloc[i]
        branch = clean_text(row[col_map['branch']])
        if not branch:
            continue
        product = clean_text(row[col_map['product']])
        brand = clean_text(row[col_map['brand']])
        colour = clean_text(row[col_map['colour']])
        size = clean_text(row[col_map['size']])
        article = clean_text(row[col_map['article']])
        mrp = clean_text(row[col_map['mrp']])
        
        try:
            qty_str = str(row[col_map['qty']]).replace(',', '').strip()
            if qty_str and qty_str not in ['nan', '']:
                qty = float(qty_str)
            else:
                qty = 0
        except:
            qty = 0
        
        if qty <= 0:
            continue
        
        items.append({
            "Branch": branch,
            "Product": product,
            "Brand": brand,
            "Colour": colour,
            "Size": size,
            "Article": article,
            "MRP": mrp,
            "Quantity": qty
        })
    return items

# ============================================
# INVENTORY BUILDER
# ============================================

def build_inventory(items):
    if not items:
        return None, None, None
    
    df_items = pd.DataFrame(items)
    df_items['SKU'] = df_items.apply(
        lambda x: f"{x['Product']}|{x['Brand']}|{x['Colour']}|{x['Size']}|{x['Article']}|{x['MRP']}", axis=1)
    all_skus = df_items['SKU'].unique()
    all_branches = df_items['Branch'].unique().tolist()
    
    inv = {}
    for branch in all_branches:
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
                "Brand": sku_row['Brand'],
                "Colour": sku_row['Colour'],
                "Size": sku_row['Size'],
                "Article": sku_row['Article'],
                "MRP": sku_row['MRP'],
                "Quantity": q
            })
        inv[branch] = pd.DataFrame(records)
    return inv, all_branches, all_skus

# ============================================
# NEW TRANSFER LOGIC: RETAIL FIRST, WAREHOUSE LAST RESORT
# ============================================

def calculate_transfers(inv, branch_targets, warehouse_name="PRAGATHI SHOES"):
    """
    Step 1: Identify surplus and deficit among retail branches only.
    Step 2: Match retail surplus to retail deficits (prioritise).
    Step 3: After retail‑to‑retail, any remaining deficits are supplied from warehouse (if warehouse has stock).
    Step 4: Warehouse never receives surplus – only sends.
    """
    if not inv:
        return pd.DataFrame()
    all_skus = next(iter(inv.values()))['SKU'].unique()
    transfers = []
    
    # Separate retail and warehouse
    retail_branches = [b for b in inv.keys() if b != warehouse_name]
    warehouse_df = inv.get(warehouse_name)
    warehouse_stock = {}
    if warehouse_df is not None:
        warehouse_stock = {row['SKU']: row['Quantity'] for _, row in warehouse_df.iterrows()}
    else:
        warehouse_stock = {}
    
    for sku in all_skus:
        # Get stock and details for retail branches
        retail_stock = {}
        details = None
        for branch in retail_branches:
            row = inv[branch][inv[branch]['SKU'] == sku]
            if not row.empty:
                q = row['Quantity'].iloc[0]
                retail_stock[branch] = q
                if details is None:
                    details = {
                        "Product": row['Product'].iloc[0],
                        "Brand": row['Brand'].iloc[0],
                        "Colour": row['Colour'].iloc[0],
                        "Size": row['Size'].iloc[0],
                        "Article": row['Article'].iloc[0],
                        "MRP": row['MRP'].iloc[0]
                    }
            else:
                retail_stock[branch] = 0
        if details is None:
            continue
        
        # Identify surplus and deficit for retail branches
        surplus = []
        deficit = []
        for branch, qty in retail_stock.items():
            target = branch_targets.get(branch, 8)
            if qty > target:
                surplus.append({"branch": branch, "excess": qty - target, "current": qty})
            elif qty < target:
                deficit.append({"branch": branch, "need": target - qty, "current": qty})
        
        # Step 1: Retail‑to‑retail transfers
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
                        "Brand": details['Brand'],
                        "Colour": details['Colour'],
                        "Size": details['Size'],
                        "Article": details['Article'],
                        "MRP": details['MRP'],
                        "From Branch": s["branch"],
                        "To Branch": d["branch"],
                        "Transfer Qty": transfer,
                        "Reason": f"Retail surplus from {s['branch']} to {d['branch']}"
                    })
                    rem -= transfer
                    d["need"] -= transfer
                    if d["need"] <= 0:
                        deficit.remove(d)
            s["excess"] = rem
        
        # Step 2: Remaining deficits are fulfilled from warehouse (if warehouse has stock)
        if deficit and warehouse_stock.get(sku, 0) > 0:
            wh_qty = warehouse_stock[sku]
            for d in deficit:
                if d["need"] <= 0:
                    continue
                transfer = min(wh_qty, d["need"])
                if transfer > 0:
                    transfers.append({
                        "SKU": sku,
                        "Product": details['Product'],
                        "Brand": details['Brand'],
                        "Colour": details['Colour'],
                        "Size": details['Size'],
                        "Article": details['Article'],
                        "MRP": details['MRP'],
                        "From Branch": f"{warehouse_name} (Warehouse)",
                        "To Branch": d["branch"],
                        "Transfer Qty": transfer,
                        "Reason": f"Warehouse supply to {d['branch']}"
                    })
                    wh_qty -= transfer
                    d["need"] -= transfer
                    if d["need"] <= 0:
                        deficit.remove(d)
            # Update warehouse stock (optional – we don't actually modify inv here)
    
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

# ============================================
# SIDEBAR – exclude warehouse from targets
# ============================================

with st.sidebar:
    st.header("⚙️ Branch Targets (Retail Only)")
    uploaded = st.file_uploader("Upload SCHOOL STOCK.xlsx", type=["xlsx"])
    st.divider()
    if st.session_state.loaded and st.session_state.branches:
        warehouse_name = "PRAGATHI SHOES"
        for b in st.session_state.branches:
            if b == warehouse_name:
                continue
            cur = st.session_state.targets.get(b, 8)
            new = st.number_input(f"{b}", min_value=1, max_value=50, value=cur, key=f"tgt_{b}")
            if new != cur:
                st.session_state.targets[b] = new
                st.session_state.transfers = calculate_transfers(st.session_state.inv, st.session_state.targets)
                st.rerun()
        st.info(f"Warehouse ({warehouse_name}) only sends stock when no retail surplus exists.")
    if st.button("🔄 Reset All Data"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

# ============================================
# MAIN APP
# ============================================

if uploaded:
    if st.session_state.file_name != uploaded.name or not st.session_state.loaded:
        with st.spinner("Loading inventory..."):
            items = parse_excel(uploaded)
            if not items:
                st.stop()
            inv, branches, all_skus = build_inventory(items)
            if inv is None:
                st.stop()
            targets = {b: 8 for b in branches if b != "PRAGATHI SHOES"}
            # Also set a dummy target for warehouse (not used but kept)
            targets["PRAGATHI SHOES"] = 0
            transfers = calculate_transfers(inv, targets)
            st.session_state.inv = inv
            st.session_state.branches = branches
            st.session_state.targets = targets
            st.session_state.transfers = transfers
            st.session_state.file_name = uploaded.name
            st.session_state.loaded = True
            st.success(f"Loaded {len(branches)} branches. Warehouse will only send stock to cover deficits after retail‑to‑retail transfers.")
            st.rerun()

if st.session_state.loaded and st.session_state.branches:
    inv = st.session_state.inv
    branches = st.session_state.branches
    targets = st.session_state.targets
    transfers = st.session_state.transfers

    # Per‑SKU shortage for each branch (only retail, warehouse ignored)
    needs = {}
    warehouse_name = "PRAGATHI SHOES"
    for b in branches:
        if b == warehouse_name:
            continue
        branch_df = inv[b]
        target_val = targets.get(b, 8)
        total_shortage = (target_val - branch_df['Quantity']).clip(lower=0).sum()
        needs[b] = int(total_shortage)

    tab_names = ["📊 Dashboard", "🚚 All Transfers", "📋 Zero Stock Anywhere"] + [f"🏪 {b}" for b in branches]
    tabs = st.tabs(tab_names)

    # Dashboard
    with tabs[0]:
        st.subheader("Branch‑wise Stock Needed (total units to reach target per SKU)")
        need_df = pd.DataFrame(list(needs.items()), columns=["Branch", "Units Needed"]).sort_values("Units Needed", ascending=False)
        st.dataframe(need_df, use_container_width=True)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📄 Download Branch Needs PDF"):
                pdf = table_to_pdf(need_df, "Branch-wise Stock Needed")
                if pdf:
                    st.download_button("Download PDF", pdf, "branch_needs.pdf")
        with col2:
            if st.button("📊 Download Branch Needs Excel"):
                excel_data = table_to_excel(need_df)
                st.download_button("Download Excel", excel_data, "branch_needs.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
        st.markdown("---")
        st.subheader("Branch Stock Summary")
        summary = []
        for b in branches:
            if b == warehouse_name:
                continue
            df = inv[b]
            tgt = targets.get(b, 8)
            tot = int(df['Quantity'].sum())
            target_total = tgt * len(df)
            zero_skus = len(df[df['Quantity'] == 0])
            low_skus = len(df[(df['Quantity'] > 0) & (df['Quantity'] < tgt)])
            summary.append({
                "Branch": b,
                "Total Stock": tot,
                "Target Total": target_total,
                "Shortage (total)": max(0, target_total - tot),
                "Surplus (total)": max(0, tot - target_total),
                "Zero SKUs": zero_skus,
                "Low SKUs": low_skus
            })
        sum_df = pd.DataFrame(summary)
        st.dataframe(sum_df, use_container_width=True)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📄 Download Branch Summary PDF"):
                pdf = table_to_pdf(sum_df, "Branch Summary")
                if pdf:
                    st.download_button("Download PDF", pdf, "branch_summary.pdf")
        with col2:
            if st.button("📊 Download Branch Summary Excel"):
                excel_data = table_to_excel(sum_df)
                st.download_button("Download Excel", excel_data, "branch_summary.xlsx")

    # All Transfers
    with tabs[1]:
        if not transfers.empty:
            disp = transfers[['From Branch', 'To Branch', 'Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP', 'Transfer Qty']]
            st.dataframe(disp, use_container_width=True)
            col1, col2 = st.columns(2)
            with col1:
                if st.button("📄 Download All Transfers PDF"):
                    pdf = table_to_pdf(disp, "All Suggested Transfers", landscape=True)
                    if pdf:
                        st.download_button("Download PDF", pdf, "all_transfers.pdf")
            with col2:
                if st.button("📊 Download All Transfers Excel"):
                    excel_data = table_to_excel(disp)
                    st.download_button("Download Excel", excel_data, "all_transfers.xlsx")
        else:
            st.success("No transfers needed.")

    # Zero Stock Anywhere
    with tabs[2]:
        zero_all = []
        retail_branches = [b for b in branches if b != warehouse_name]
        if retail_branches:
            first = inv[retail_branches[0]]
            if not first.empty:
                for sku in first['SKU'].unique():
                    total = 0
                    info = None
                    for b in retail_branches:
                        row = inv[b][inv[b]['SKU'] == sku]
                        if not row.empty:
                            total += row['Quantity'].iloc[0]
                            if info is None:
                                info = {
                                    "Product": row['Product'].iloc[0],
                                    "Brand": row['Brand'].iloc[0],
                                    "Colour": row['Colour'].iloc[0],
                                    "Size": row['Size'].iloc[0],
                                    "Article": row['Article'].iloc[0],
                                    "MRP": row['MRP'].iloc[0]
                                }
                    if total == 0 and info:
                        zero_all.append(info)
        zero_df = pd.DataFrame(zero_all)
        if not zero_df.empty:
            st.error(f"{len(zero_df)} products have zero stock in **all retail branches**.")
            st.dataframe(zero_df[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP']], use_container_width=True)
            col1, col2 = st.columns(2)
            with col1:
                if st.button("📄 Download Zero Anywhere PDF"):
                    pdf = table_to_pdf(zero_df[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP']],
                                       "Products with Zero Stock Across All Retail Branches")
                    if pdf:
                        st.download_button("Download PDF", pdf, "zero_anywhere.pdf")
            with col2:
                if st.button("📊 Download Zero Anywhere Excel"):
                    excel_data = table_to_excel(zero_df[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP']])
                    st.download_button("Download Excel", excel_data, "zero_anywhere.xlsx")
        else:
            st.success("✅ Every product has stock in at least one retail branch.")
            st.info("Note: Individual branches may still have zero‑stock items – see each branch tab (Table 1).")

    # Branch‑specific tabs (including warehouse)
    for idx, branch in enumerate(branches):
        with tabs[idx+3]:
            branch_df = inv[branch].copy()
            if branch_df.empty:
                st.info(f"No data for {branch}")
                continue
            # For warehouse, set a high "target" (not used for transfer logic)
            if branch == warehouse_name:
                tgt = 999999  # effectively no target
                min_level = 1
            else:
                tgt = targets.get(branch, 8)
                min_level = max(1, tgt // 2)

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Total Stock", int(branch_df['Quantity'].sum()))
            c2.metric("SKUs", len(branch_df))
            c3.metric("Zero Stock", len(branch_df[branch_df['Quantity'] == 0]))
            c4.metric("Low Stock", len(branch_df[(branch_df['Quantity'] > 0) & (branch_df['Quantity'] < min_level)]))
            c5.metric("Surplus", len(branch_df[branch_df['Quantity'] > tgt]))

            # Zero Stock Table with article AND brand search
            st.subheader("Table 1: Zero Stock Items")
            zero = branch_df[branch_df['Quantity'] == 0].copy()
            if not zero.empty:
                col1, col2 = st.columns(2)
                with col1:
                    search_article = st.text_input(f"🔍 Search Article", key=f"search_article_{branch}")
                with col2:
                    search_brand = st.text_input(f"🏷️ Search Brand", key=f"search_brand_{branch}")
                if search_article:
                    zero = zero[zero['Article'].str.contains(search_article, case=False, na=False)]
                if search_brand:
                    zero = zero[zero['Brand'].str.contains(search_brand, case=False, na=False)]
                
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
                            st.session_state.transfers = calculate_transfers(st.session_state.inv, st.session_state.targets)
                            st.success(f"Deleted {len(selected)} item(s) from {branch}")
                            st.rerun()
                        else:
                            st.warning("No items selected")
                with col2:
                    if st.button(f"🔄 Reset Branch", key=f"reset_{branch}"):
                        st.session_state.inv[branch] = inv[branch].copy()
                        st.session_state.transfers = calculate_transfers(st.session_state.inv, st.session_state.targets)
                        st.success(f"Reset {branch} to original")
                        st.rerun()
                if st.button(f"📄 PDF - Zero Stock", key=f"zero_pdf_{branch}"):
                    pdf = table_to_pdf(zero[['Product','Brand','Size','Colour','Article','MRP']], f"{branch} - Zero Stock")
                    if pdf:
                        st.download_button("Download PDF", pdf, f"{branch}_zero.pdf")
                if st.button(f"📊 Excel - Zero Stock", key=f"zero_excel_{branch}"):
                    excel_data = table_to_excel(zero[['Product','Brand','Size','Colour','Article','MRP']])
                    st.download_button("Download Excel", excel_data, f"{branch}_zero.xlsx")
            else:
                st.success("No zero stock items")

            # Low Stock Table
            st.subheader("Table 2: Low Stock Items")
            low = branch_df[(branch_df['Quantity'] > 0) & (branch_df['Quantity'] < min_level)].copy()
            if not low.empty:
                low_disp = low[['Product','Brand','Size','Colour','Article','MRP','Quantity']].copy()
                low_disp.rename(columns={'Quantity':'Currently Available'}, inplace=True)
                low_disp['Target'] = tgt
                st.dataframe(low_disp, use_container_width=True)
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"📄 PDF - Low Stock", key=f"low_pdf_{branch}"):
                        pdf = table_to_pdf(low_disp, f"{branch} - Low Stock Items")
                        if pdf:
                            st.download_button("Download PDF", pdf, f"{branch}_low.pdf")
                with col2:
                    if st.button(f"📊 Excel - Low Stock", key=f"low_excel_{branch}"):
                        excel_data = table_to_excel(low_disp)
                        st.download_button("Download Excel", excel_data, f"{branch}_low.xlsx")
            else:
                st.success("No low stock items")

            # Complete Inventory
            st.subheader("Table 3: Complete Inventory")
            full = branch_df[['Product','Brand','Size','Colour','Article','MRP','Quantity']].copy()
            full.rename(columns={'Quantity':'Currently Available'}, inplace=True)
            full['Status'] = full['Currently Available'].apply(
                lambda x: 'Zero' if x==0 else ('Low' if x<min_level else ('Surplus' if x>tgt else 'OK'))
            )
            st.dataframe(full, use_container_width=True)
            col1, col2 = st.columns(2)
            with col1:
                if st.button(f"📄 PDF - Complete Inventory", key=f"full_pdf_{branch}"):
                    pdf = table_to_pdf(full, f"{branch} - Complete Inventory", landscape=True)
                    if pdf:
                        st.download_button("Download PDF", pdf, f"{branch}_full.pdf")
            with col2:
                if st.button(f"📊 Excel - Complete Inventory", key=f"full_excel_{branch}"):
                    excel_data = table_to_excel(full)
                    st.download_button("Download Excel", excel_data, f"{branch}_full.xlsx")

            # Transfers involving this branch
            br_trans = get_branch_transfers(transfers, branch)
            if not br_trans.empty:
                st.subheader("Suggested Transfers")
                disp = br_trans[['Product','Brand','Size','Colour','From Branch','To Branch','Transfer Qty']]
                st.dataframe(disp, use_container_width=True)
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"📄 PDF - Transfers", key=f"trans_pdf_{branch}"):
                        pdf = table_to_pdf(disp, f"{branch} - Transfer Orders", landscape=True)
                        if pdf:
                            st.download_button("Download PDF", pdf, f"{branch}_transfers.pdf")
                with col2:
                    if st.button(f"📊 Excel - Transfers", key=f"trans_excel_{branch}"):
                        excel_data = table_to_excel(disp)
                        st.download_button("Download Excel", excel_data, f"{branch}_transfers.xlsx")

else:
    st.info("👈 Upload your SCHOOL STOCK.xlsx file")
    st.markdown("""
    ## Pragathi Shoes – Complete Stock Transfer System

    **New features:**
    - **Excel export** for every table (PDF and Excel side by side).
    - **Transfer logic prioritises retail‑to‑retail** – warehouse only supplies deficits when no retail surplus exists.
    - Warehouse **never receives surplus** from retail branches.
    - Warehouse target is not displayed (acts as pure distributor).

    ### How transfers work
    1. For each SKU, the system identifies retail branches with surplus (stock > target) and deficit (stock < target).
    2. Surplus retail branches send to deficit retail branches as much as possible.
    3. If deficits remain and the warehouse has stock, the warehouse sends to those deficit branches.
    4. Warehouse never takes stock from retail branches.

    ### Zero‑stock tables
    - Search by **Article** and/or **Brand**.
    - Delete selected rows (per branch) and reset to original.
    - Export both PDF and Excel.
    """)
