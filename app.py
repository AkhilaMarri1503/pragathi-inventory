import streamlit as st
import pandas as pd
import numpy as np
from fpdf import FPDF
from datetime import datetime
import re
import io

st.set_page_config(page_title="Pragathi Shoes - Complete Transfer System", layout="wide")
st.title("👞 Pragathi Shoes – Complete Stock Transfer System")
st.markdown("**Global filters, zero‑stock deletion with Select All, warehouse report, grand totals**")

# ============================================
# HELPER FUNCTIONS
# ============================================

def clean_text(text):
    if pd.isna(text):
        return ""
    text = str(text)
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    return text.strip()

def add_total_row(df, numeric_cols):
    """Append a total row to dataframe for specified numeric columns."""
    if df.empty:
        return df
    total_row = {col: "" for col in df.columns}
    for col in numeric_cols:
        if col in df.columns:
            total_row[col] = df[col].sum()
    total_row[df.columns[0]] = "**GRAND TOTAL**"
    return pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)

def table_to_excel(df):
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
# EXCEL PARSER (reads Brand column)
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
# TRANSFER LOGIC (retail first, warehouse last)
# ============================================

def calculate_transfers(inv, branch_targets, warehouse_name="PRAGATHI SHOES"):
    retail_branches = [b for b in inv.keys() if b != warehouse_name]
    all_skus = next(iter(inv.values()))['SKU'].unique()
    transfers = []
    
    warehouse_df = inv.get(warehouse_name)
    warehouse_stock = {}
    if warehouse_df is not None:
        warehouse_stock = {row['SKU']: row['Quantity'] for _, row in warehouse_df.iterrows()}
    
    for sku in all_skus:
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
        
        surplus = []
        deficit = []
        for branch, qty in retail_stock.items():
            target = branch_targets.get(branch, 8)
            if qty > target:
                surplus.append({"branch": branch, "excess": qty - target, "current": qty})
            elif qty < target:
                deficit.append({"branch": branch, "need": target - qty, "current": qty})
        
        # Retail‑to‑retail
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
        
        # Warehouse top‑up for remaining deficits
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
    return pd.DataFrame(transfers) if transfers else pd.DataFrame()

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
    st.session_state.filter_brands = []
    st.session_state.filter_articles = []

# ============================================
# SIDEBAR – Global Filters & Retail Targets
# ============================================

with st.sidebar:
    st.header("⚙️ Configuration")
    uploaded = st.file_uploader("Upload SCHOOL STOCK.xlsx", type=["xlsx"])
    
    if st.session_state.loaded:
        st.divider()
        st.subheader("🌍 Global Filters (All Branches)")
        retail_branches = [b for b in st.session_state.branches if b != "PRAGATHI SHOES"]
        all_brands = set()
        all_articles = set()
        for b in retail_branches:
            df = st.session_state.inv[b]
            all_brands.update(df['Brand'].unique())
            all_articles.update(df['Article'].unique())
        brand_options = sorted(list(all_brands))
        article_options = sorted(list(all_articles))
        
        selected_brands = st.multiselect("Brands", brand_options, default=st.session_state.filter_brands)
        selected_articles = st.multiselect("Articles", article_options, default=st.session_state.filter_articles)
        st.session_state.filter_brands = selected_brands
        st.session_state.filter_articles = selected_articles
        
        st.divider()
        st.subheader("🎯 Branch Targets (Retail Only)")
        warehouse_name = "PRAGATHI SHOES"
        for b in retail_branches:
            cur = st.session_state.targets.get(b, 8)
            new = st.number_input(f"{b}", min_value=1, max_value=50, value=cur, key=f"tgt_{b}")
            if new != cur:
                st.session_state.targets[b] = new
                st.session_state.transfers = calculate_transfers(st.session_state.inv, st.session_state.targets)
                st.rerun()
        st.info("Warehouse only sends stock when no retail surplus exists.")
    
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
            targets["PRAGATHI SHOES"] = 0
            transfers = calculate_transfers(inv, targets)
            st.session_state.inv = inv
            st.session_state.branches = branches
            st.session_state.targets = targets
            st.session_state.transfers = transfers
            st.session_state.file_name = uploaded.name
            st.session_state.loaded = True
            # Initialise filters with all values
            retail_branches = [b for b in branches if b != "PRAGATHI SHOES"]
            all_brands = set()
            all_articles = set()
            for b in retail_branches:
                df = inv[b]
                all_brands.update(df['Brand'].unique())
                all_articles.update(df['Article'].unique())
            st.session_state.filter_brands = list(all_brands)
            st.session_state.filter_articles = list(all_articles)
            st.success(f"Loaded {len(branches)} branches. Warehouse acts as last‑resort distributor.")
            st.rerun()

if st.session_state.loaded and st.session_state.branches:
    inv = st.session_state.inv
    branches = st.session_state.branches
    targets = st.session_state.targets
    transfers = st.session_state.transfers
    filter_brands = st.session_state.filter_brands
    filter_articles = st.session_state.filter_articles
    warehouse_name = "PRAGATHI SHOES"
    retail_branches = [b for b in branches if b != warehouse_name]

    # Apply global filters to each branch's inventory (for display)
    filtered_inv = {}
    for b in branches:
        df = inv[b].copy()
        if b != warehouse_name:
            if filter_brands:
                df = df[df['Brand'].str.contains('|'.join(filter_brands), case=False, na=False)]
            if filter_articles:
                df = df[df['Article'].str.contains('|'.join(filter_articles), case=False, na=False)]
        filtered_inv[b] = df

    # Dashboard – branch shortages
    needs = {}
    for b in retail_branches:
        branch_df = filtered_inv[b]
        target_val = targets.get(b, 8)
        total_shortage = (target_val - branch_df['Quantity']).clip(lower=0).sum()
        needs[b] = int(total_shortage)

    # Tab names: Dashboard, All Transfers, Warehouse Report, then each retail branch
    tab_names = ["📊 Dashboard", "🚚 All Transfers", "🏭 Warehouse Report"] + [f"🏪 {b}" for b in retail_branches]
    tabs = st.tabs(tab_names)

    # ========== DASHBOARD ==========
    with tabs[0]:
        st.subheader("Branch‑wise Stock Needed (total units to reach target per SKU)")
        need_df = pd.DataFrame(list(needs.items()), columns=["Branch", "Units Needed"]).sort_values("Units Needed", ascending=False)
        need_df_with_total = add_total_row(need_df, ["Units Needed"])
        st.dataframe(need_df_with_total, use_container_width=True)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📄 Branch Needs PDF"):
                pdf = table_to_pdf(need_df_with_total, "Branch-wise Stock Needed")
                if pdf:
                    st.download_button("Download PDF", pdf, "branch_needs.pdf")
        with col2:
            if st.button("📊 Branch Needs Excel"):
                excel_data = table_to_excel(need_df_with_total)
                st.download_button("Download Excel", excel_data, "branch_needs.xlsx")
        
        st.markdown("---")
        st.subheader("Branch Stock Summary (Filtered)")
        summary = []
        for b in retail_branches:
            df = filtered_inv[b]
            tgt = targets.get(b, 8)
            tot = int(df['Quantity'].sum())
            target_total = tgt * len(df)
            zero_skus = len(df[df['Quantity'] == 0])
            low_skus = len(df[(df['Quantity'] > 0) & (df['Quantity'] < tgt)])
            summary.append({
                "Branch": b,
                "Total Stock": tot,
                "Target Total": target_total,
                "Shortage": max(0, target_total - tot),
                "Surplus": max(0, tot - target_total),
                "Zero SKUs": zero_skus,
                "Low SKUs": low_skus
            })
        sum_df = pd.DataFrame(summary)
        sum_df_with_total = add_total_row(sum_df, ["Total Stock", "Target Total", "Shortage", "Surplus", "Zero SKUs", "Low SKUs"])
        st.dataframe(sum_df_with_total, use_container_width=True)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📄 Summary PDF"):
                pdf = table_to_pdf(sum_df_with_total, "Branch Summary")
                if pdf:
                    st.download_button("Download PDF", pdf, "branch_summary.pdf")
        with col2:
            if st.button("📊 Summary Excel"):
                excel_data = table_to_excel(sum_df_with_total)
                st.download_button("Download Excel", excel_data, "branch_summary.xlsx")

    # ========== ALL TRANSFERS ==========
    with tabs[1]:
        if not transfers.empty:
            disp = transfers[['From Branch', 'To Branch', 'Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP', 'Transfer Qty']]
            disp_with_total = add_total_row(disp, ["Transfer Qty"])
            st.dataframe(disp_with_total, use_container_width=True)
            col1, col2 = st.columns(2)
            with col1:
                if st.button("📄 All Transfers PDF"):
                    pdf = table_to_pdf(disp_with_total, "All Suggested Transfers", landscape=True)
                    if pdf:
                        st.download_button("Download PDF", pdf, "all_transfers.pdf")
            with col2:
                if st.button("📊 All Transfers Excel"):
                    excel_data = table_to_excel(disp_with_total)
                    st.download_button("Download Excel", excel_data, "all_transfers.xlsx")
        else:
            st.success("No transfers needed.")

    # ========== WAREHOUSE REPORT (outgoing only) ==========
    with tabs[2]:
        st.subheader("🏭 Warehouse Outgoing Transfers Report")
        wh_outgoing = transfers[transfers['From Branch'].str.contains(warehouse_name, case=False, na=False)].copy()
        if not wh_outgoing.empty:
            wh_report = wh_outgoing[['To Branch', 'Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP', 'Transfer Qty']]
            wh_report_with_total = add_total_row(wh_report, ["Transfer Qty"])
            st.dataframe(wh_report_with_total, use_container_width=True)
            col1, col2 = st.columns(2)
            with col1:
                if st.button("📄 Warehouse Report PDF"):
                    pdf = table_to_pdf(wh_report_with_total, "Warehouse Outgoing Transfers", landscape=True)
                    if pdf:
                        st.download_button("Download PDF", pdf, "warehouse_transfers.pdf")
            with col2:
                if st.button("📊 Warehouse Report Excel"):
                    excel_data = table_to_excel(wh_report_with_total)
                    st.download_button("Download Excel", excel_data, "warehouse_transfers.xlsx")
        else:
            st.info("No transfers originating from warehouse.")

    # ========== BRANCH TABS (5 sub‑tabs each) ==========
    for idx, branch in enumerate(retail_branches):
        with tabs[idx+3]:
            branch_df = filtered_inv[branch]  # already filtered
            tgt = targets.get(branch, 8)
            min_level = max(1, tgt // 2)
            
            # 5 sub‑tabs: Zero Stock, Available Stock, Required Stock, Warehouse Top‑up, Branch Transfer Data
            sub_tab0, sub_tab1, sub_tab2, sub_tab3, sub_tab4 = st.tabs([
                "🔴 Zero Stock Items", "📦 Available Stock", "⚠️ Required Stock", 
                "🏭 Warehouse Top‑up", "🔄 Branch Transfer Data"
            ])
            
            # ----- Sub‑tab 0: Zero Stock Items (with search, select all, delete, reset) -----
            with sub_tab0:
                st.subheader(f"Zero Stock Items – {branch}")
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
                    
                    # Prepare display dataframe
                    display_zero = zero[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP']].reset_index(drop=True)
                    
                    # Add Select All checkbox
                    select_all_key = f"select_all_{branch}"
                    if select_all_key not in st.session_state:
                        st.session_state[select_all_key] = False
                    
                    select_all = st.checkbox("✅ Select All", key=f"select_all_check_{branch}")
                    if select_all:
                        st.session_state[select_all_key] = True
                    else:
                        st.session_state[select_all_key] = False
                    
                    # Create dataframe with Select column
                    disp_zero = display_zero.copy()
                    disp_zero.insert(0, "Select", st.session_state[select_all_key])
                    
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
                                # Recalculate transfers after deletion
                                st.session_state.transfers = calculate_transfers(st.session_state.inv, st.session_state.targets)
                                st.success(f"Deleted {len(selected)} item(s) from {branch}")
                                st.rerun()
                            else:
                                st.warning("No items selected")
                    with col2:
                        if st.button(f"🔄 Reset Branch Data", key=f"reset_{branch}"):
                            st.session_state.inv[branch] = inv[branch].copy()
                            st.session_state.transfers = calculate_transfers(st.session_state.inv, st.session_state.targets)
                            st.success(f"Reset {branch} to original")
                            st.rerun()
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button(f"📄 PDF – Zero Stock", key=f"zero_pdf_{branch}"):
                            pdf = table_to_pdf(zero[['Product','Brand','Size','Colour','Article','MRP']], f"{branch} - Zero Stock")
                            if pdf:
                                st.download_button("Download PDF", pdf, f"{branch}_zero.pdf")
                    with col2:
                        if st.button(f"📊 Excel – Zero Stock", key=f"zero_excel_{branch}"):
                            excel_data = table_to_excel(zero[['Product','Brand','Size','Colour','Article','MRP']])
                            st.download_button("Download Excel", excel_data, f"{branch}_zero.xlsx")
                else:
                    st.success("No zero stock items in this branch.")
            
            # ----- Sub‑tab 1: Available Stock -----
            with sub_tab1:
                st.subheader(f"Available Stock – {branch}")
                avail = branch_df[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP', 'Quantity']].copy()
                avail.rename(columns={'Quantity': 'Currently Available'}, inplace=True)
                avail_with_total = add_total_row(avail, ["Currently Available"])
                st.dataframe(avail_with_total, use_container_width=True)
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"📄 PDF – Available", key=f"avail_pdf_{branch}"):
                        pdf = table_to_pdf(avail_with_total, f"{branch} - Available Stock", landscape=True)
                        if pdf:
                            st.download_button("Download PDF", pdf, f"{branch}_available.pdf")
                with col2:
                    if st.button(f"📊 Excel – Available", key=f"avail_excel_{branch}"):
                        excel_data = table_to_excel(avail_with_total)
                        st.download_button("Download Excel", excel_data, f"{branch}_available.xlsx")
            
            # ----- Sub‑tab 2: Required Stock (shortage) -----
            with sub_tab2:
                st.subheader(f"Required Stock – {branch}")
                shortage_df = branch_df[branch_df['Quantity'] < tgt].copy()
                if not shortage_df.empty:
                    req = shortage_df[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP', 'Quantity']].copy()
                    req['Required'] = tgt - req['Quantity']
                    req.rename(columns={'Quantity': 'Currently Available'}, inplace=True)
                    req_with_total = add_total_row(req, ["Currently Available", "Required"])
                    st.dataframe(req_with_total, use_container_width=True)
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button(f"📄 PDF – Required", key=f"req_pdf_{branch}"):
                            pdf = table_to_pdf(req_with_total, f"{branch} - Required Stock", landscape=True)
                            if pdf:
                                st.download_button("Download PDF", pdf, f"{branch}_required.pdf")
                    with col2:
                        if st.button(f"📊 Excel – Required", key=f"req_excel_{branch}"):
                            excel_data = table_to_excel(req_with_total)
                            st.download_button("Download Excel", excel_data, f"{branch}_required.xlsx")
                else:
                    st.success(f"All SKUs in {branch} meet or exceed target ({tgt}).")
            
            # ----- Sub‑tab 3: Warehouse Top‑up (transfers from warehouse to this branch) -----
            with sub_tab3:
                st.subheader(f"Warehouse Top‑up – {branch}")
                wh_to_branch = transfers[transfers['To Branch'] == branch].copy()
                wh_to_branch = wh_to_branch[wh_to_branch['From Branch'].str.contains(warehouse_name, case=False, na=False)]
                if not wh_to_branch.empty:
                    topup = wh_to_branch[['Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP', 'Transfer Qty']]
                    topup.rename(columns={'Transfer Qty': 'Suggested Transfer'}, inplace=True)
                    topup_with_total = add_total_row(topup, ["Suggested Transfer"])
                    st.dataframe(topup_with_total, use_container_width=True)
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button(f"📄 PDF – Top‑up", key=f"topup_pdf_{branch}"):
                            pdf = table_to_pdf(topup_with_total, f"{branch} - Warehouse Top‑up", landscape=True)
                            if pdf:
                                st.download_button("Download PDF", pdf, f"{branch}_topup.pdf")
                    with col2:
                        if st.button(f"📊 Excel – Top‑up", key=f"topup_excel_{branch}"):
                            excel_data = table_to_excel(topup_with_total)
                            st.download_button("Download Excel", excel_data, f"{branch}_topup.xlsx")
                else:
                    st.info(f"No warehouse top‑up suggested for {branch}.")
            
            # ----- Sub‑tab 4: Branch Transfer Data (outgoing + incoming) -----
            with sub_tab4:
                st.subheader(f"Branch Transfer Data – {branch}")
                branch_transfers = transfers[(transfers['From Branch'] == branch) | (transfers['To Branch'] == branch)].copy()
                if not branch_transfers.empty:
                    # Outgoing
                    st.markdown("#### 📤 Outgoing (from this branch)")
                    outgoing = branch_transfers[branch_transfers['From Branch'] == branch].copy()
                    if not outgoing.empty:
                        out_disp = outgoing[['To Branch', 'Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP', 'Transfer Qty']]
                        out_disp.rename(columns={'To Branch': 'Destination', 'Transfer Qty': 'Quantity'}, inplace=True)
                        out_with_total = add_total_row(out_disp, ["Quantity"])
                        st.dataframe(out_with_total, use_container_width=True)
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button(f"📄 PDF – Outgoing", key=f"out_pdf_{branch}"):
                                pdf = table_to_pdf(out_with_total, f"{branch} - Outgoing Transfers", landscape=True)
                                if pdf:
                                    st.download_button("Download PDF", pdf, f"{branch}_outgoing.pdf")
                        with col2:
                            if st.button(f"📊 Excel – Outgoing", key=f"out_excel_{branch}"):
                                excel_data = table_to_excel(out_with_total)
                                st.download_button("Download Excel", excel_data, f"{branch}_outgoing.xlsx")
                    else:
                        st.info("No outgoing transfers.")
                    
                    # Incoming
                    st.markdown("#### 📥 Incoming (to this branch)")
                    incoming = branch_transfers[branch_transfers['To Branch'] == branch].copy()
                    if not incoming.empty:
                        in_disp = incoming[['From Branch', 'Product', 'Brand', 'Size', 'Colour', 'Article', 'MRP', 'Transfer Qty']]
                        in_disp.rename(columns={'From Branch': 'Source', 'Transfer Qty': 'Quantity'}, inplace=True)
                        in_with_total = add_total_row(in_disp, ["Quantity"])
                        st.dataframe(in_with_total, use_container_width=True)
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button(f"📄 PDF – Incoming", key=f"in_pdf_{branch}"):
                                pdf = table_to_pdf(in_with_total, f"{branch} - Incoming Transfers", landscape=True)
                                if pdf:
                                    st.download_button("Download PDF", pdf, f"{branch}_incoming.pdf")
                        with col2:
                            if st.button(f"📊 Excel – Incoming", key=f"in_excel_{branch}"):
                                excel_data = table_to_excel(in_with_total)
                                st.download_button("Download Excel", excel_data, f"{branch}_incoming.xlsx")
                    else:
                        st.info("No incoming transfers.")
                else:
                    st.info("No transfers involving this branch.")

else:
    st.info("👈 Upload your SCHOOL STOCK.xlsx file to begin.")
    st.markdown("""
    ## Complete Features

    - **Global Brand & Article filters** (affect all retail branch views).
    - **Zero stock table** per branch – search by Article/Brand, **Select All** checkbox, multi‑select delete, reset, PDF/Excel.
    - **Available Stock**, **Required Stock**, **Warehouse Top‑up**, and **Branch Transfer Data** (split into Outgoing/Incoming) sub‑tabs.
    - **Grand total rows** at the end of numeric columns.
    - **Warehouse report** showing all outgoing transfers.
    - **PDF and Excel export** for every table.
    - Transfer logic: retail‑to‑retail first, warehouse supplies only remaining deficits.
    """)
