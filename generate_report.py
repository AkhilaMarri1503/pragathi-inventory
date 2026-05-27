import pandas as pd
import io
from itertools import product

def generate_inventory_report(uploaded_file):
    """
    uploaded_file: a file-like object (e.g., from st.file_uploader)
    Returns: a bytes object of the generated Excel file
    """
    # Read the uploaded Excel file
    df_raw = pd.read_excel(uploaded_file, sheet_name='Sheet1', skiprows=3)
    df_raw.columns = ['Branch', 'Product', 'Brand', 'Article', 'Size', 'Colour', 'Mrp', 'CLQTY', 'CLVAL', 'Note']
    df_raw = df_raw.dropna(subset=['Branch'])
    df_raw = df_raw[df_raw['Branch'].str.strip() != '']
    df_raw['Quantity'] = pd.to_numeric(df_raw['CLQTY'], errors='coerce').fillna(0).astype(int)
    df = df_raw[['Branch', 'Product', 'Brand', 'Article', 'Size', 'Colour', 'Quantity']].copy()

    # Filter out PARAGON
    df = df[~df['Brand'].str.contains('PARAGON', case=False, na=False)]

    branches = sorted(df['Branch'].unique())
    sku_columns = ['Product', 'Brand', 'Article', 'Size', 'Colour']
    all_skus = df[sku_columns].drop_duplicates().values.tolist()

    # Create full grid
    full_index = pd.MultiIndex.from_product([branches, range(len(all_skus))], names=['Branch', 'SKU_id'])
    full_df = pd.DataFrame(index=full_index).reset_index()
    sku_df = pd.DataFrame(all_skus, columns=sku_columns)
    sku_df['SKU_id'] = sku_df.index
    full_df = full_df.merge(sku_df, on='SKU_id', how='left')
    full_df = full_df.drop(columns=['SKU_id'])
    actual = df.groupby(['Branch'] + sku_columns)['Quantity'].sum().reset_index()
    full_df = full_df.merge(actual, on=['Branch'] + sku_columns, how='left')
    full_df['Quantity'] = full_df['Quantity'].fillna(0).astype(int)

    def is_popular_branch(branch_name):
        return 'POPULAR' in branch_name.upper()

    full_df['Need'] = full_df['Branch'].apply(lambda b: 12 if is_popular_branch(b) else 6)
    full_df['Shortfall'] = (full_df['Need'] - full_df['Quantity']).clip(lower=0)
    full_df['Surplus'] = (full_df['Quantity'] - full_df['Need']).clip(lower=0)

    # Transfer generation
    transfer_records = []
    for sku in sku_df[sku_columns].itertuples(index=False):
        sku_dict = {col: getattr(sku, col) for col in sku_columns}
        mask = (full_df[sku_columns] == pd.Series(sku_dict)).all(axis=1)
        sku_data = full_df[mask].copy()
        surplus_list = sku_data[sku_data['Surplus'] > 0][['Branch', 'Surplus']].values.tolist()
        shortfall_list = sku_data[sku_data['Shortfall'] > 0][['Branch', 'Shortfall']].values.tolist()
        i, j = 0, 0
        while i < len(surplus_list) and j < len(shortfall_list):
            surp_branch, surp_qty = surplus_list[i]
            short_branch, short_qty = shortfall_list[j]
            transfer = min(surp_qty, short_qty)
            if transfer > 0:
                transfer_records.append({
                    'Source': surp_branch,
                    'Destination': short_branch,
                    'Product': sku_dict['Product'],
                    'Brand': sku_dict['Brand'],
                    'Article': sku_dict['Article'],
                    'Size': sku_dict['Size'],
                    'Colour': sku_dict['Colour'],
                    'Quantity': transfer
                })
                surplus_list[i][1] -= transfer
                shortfall_list[j][1] -= transfer
            if surplus_list[i][1] == 0:
                i += 1
            if shortfall_list[j][1] == 0:
                j += 1
    transfers_df = pd.DataFrame(transfer_records)

    # Write to Excel in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for branch in branches:
            avail = full_df[full_df['Branch'] == branch][['Product','Brand','Article','Size','Colour','Quantity']].copy()
            avail.loc[len(avail)] = ['GRAND TOTAL', '', '', '', '', avail['Quantity'].sum()]
            avail.to_excel(writer, sheet_name=f'{branch} - Available Stock', index=False)

            req = full_df[full_df['Branch'] == branch][['Product','Brand','Article','Size','Colour','Need']].copy()
            req.loc[len(req)] = ['GRAND TOTAL', '', '', '', '', req['Need'].sum()]
            req.to_excel(writer, sheet_name=f'{branch} - Required Stock', index=False)

            outgoing = transfers_df[transfers_df['Source'] == branch].copy()
            if not outgoing.empty:
                outgoing = outgoing[['Destination','Product','Brand','Article','Size','Colour','Quantity']]
                outgoing.loc[len(outgoing)] = ['GRAND TOTAL', '', '', '', '', '', outgoing['Quantity'].sum()]
            else:
                outgoing = pd.DataFrame(columns=['Destination','Product','Brand','Article','Size','Colour','Quantity'])
                outgoing.loc[0] = ['GRAND TOTAL', '', '', '', '', '', 0]
            outgoing.to_excel(writer, sheet_name=f'{branch} - Outgoing Transfers', index=False)

            incoming = transfers_df[transfers_df['Destination'] == branch].copy()
            if not incoming.empty:
                incoming = incoming[['Source','Product','Brand','Article','Size','Colour','Quantity']]
                incoming.loc[len(incoming)] = ['GRAND TOTAL', '', '', '', '', '', incoming['Quantity'].sum()]
            else:
                incoming = pd.DataFrame(columns=['Source','Product','Brand','Article','Size','Colour','Quantity'])
                incoming.loc[0] = ['GRAND TOTAL', '', '', '', '', '', 0]
            incoming.to_excel(writer, sheet_name=f'{branch} - Incoming Transfers', index=False)

        # Summary sheet
        if not transfers_df.empty:
            all_trans = transfers_df[['Source','Destination','Product','Brand','Article','Size','Colour','Quantity']].copy()
            all_trans.loc[len(all_trans)] = ['GRAND TOTAL', '', '', '', '', '', '', all_trans['Quantity'].sum()]
        else:
            all_trans = pd.DataFrame(columns=['Source','Destination','Product','Brand','Article','Size','Colour','Quantity'])
            all_trans.loc[0] = ['GRAND TOTAL', '', '', '', '', '', '', 0]
        all_trans.to_excel(writer, sheet_name='All Transfers (Summary)', index=False)

    output.seek(0)
    return output.getvalue()
