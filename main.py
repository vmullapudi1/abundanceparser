import csv
import re
from collections import namedtuple
from typing import List, Tuple, Dict

import numpy as np
import pandas as pd
import toml
from Bio import SeqRecord, SeqIO

# Path to configuration toml file
config_file: str = "config.toml"

FileTuple = namedtuple("FileTuple", ['FileName', 'FileData'])


def convert_fileidtoabundaceformat(ftuple, fileid_col_name, abundance_col_name):
    file_data = ftuple.FileData
    grouped = file_data.groupby(fileid_col_name)
    # for every row with the same fileID
    outputdf = pd.DataFrame()
    abundance_col_titles = []
    for fileidgroup in grouped:
        # create a new DataFrame with a new abundance id title and copy the abundances over
        current_fileid = fileidgroup[0]
        data_same_fileid = fileidgroup[1]
        colname = sanitize_str_for_dataframe_index("Abundance:" + current_fileid)
        abundance_col_titles.append(colname)
        current_abundances = data_same_fileid[sanitize_str_for_dataframe_index(abundance_col_name)].tolist()
        data_same_fileid = data_same_fileid.assign(**{colname: current_abundances})
        # frag_by_fileid.append(data_same_fileid)
        outputdf = pd.concat([outputdf, data_same_fileid], sort=True)
    return abundance_col_titles, FileTuple(FileName=ftuple[0], FileData=outputdf)


def main():
    # Get the desired configuration-------------------------------------------------------------------------------------
    configuration: dict = toml.load(config_file)

    # I/O files
    input_file = configuration['input']["input_files"]
    protein_fasta_files: List[str] = configuration['input']['prot_seq_fasta']
    residue_output_name_stub = configuration['output']['residue_output_name_stub']
    output_directory = configuration['output']['output_directory']

    # Get the regular expressions to use for parsing
    regex_conf = toml.load(configuration['parser_config']['regex']['regex_file'])
    mod_parsing_regex_to_use = configuration['parser_config']['regex']['mod_parsing_regex']
    mod_regex = regex_conf['regex'][mod_parsing_regex_to_use]

    # config if using the pre-provided master localizations
    use_mod_in_master_prot: bool = configuration['parser_config']['master']['use']
    if use_mod_in_master_prot:  # put this behind conditional so if master parsing isn't desired it won't complain if
        # the config file isn't completely correct/filled out with regards to the master protein parsing settings
        master_prot_name: bool = configuration['parser_config']['master']['master_protein_name']
        master_protein_fasta_id = configuration['parser_config']['master']['master_protein_fasta_ID']
        master_regex_to_use = configuration['parser_config']['regex']['pos_master_regex']
        master_regex = regex_conf['regex'][master_regex_to_use]
    # Config for parsing and analyzing the data
    # The abundance columns to parse out abundances from for use in residue and peptide modification calculations
    abundance_col_titles = configuration['parser_config']['abundance_col_titles']
    # todo implement fileID splitting (pre-processing step?)
    # if the file_id column is used we expect to see only one column of abundances
    using_file_id_column = configuration['parser_config']['using_fileID_column']
    if using_file_id_column:
        fileid_col_name = configuration['parser_config']['fileid_col_name']
    should_calculate_peptide_modifications = True  # configuration['parser_config']['calculate_peptide_modifications']
    if should_calculate_peptide_modifications:
        peptide_output_name_stub = configuration['output']['peptide_output_name_stub']

    # End of configuration reading--------------------------------------------------------------------------------------

    # Read input files--------------------------------------------------------------------------------------------------
    # input_data is a list of FileTuples (filename, pandas DataFrame of the csv)
    input_data: List[FileTuple] = ingest_file_data(files=input_file)
    protein_seq_records: Dict = get_protein_sequences(protein_fasta_files)
    # End of Data file reading------------------------------------------------------------------------------------------

    # get the sequence from the without the cleavage annotations, etc. from the annotated sequence column
    data = (gen_raw_sequences(ftuple) for ftuple in input_data)
    if using_file_id_column:
        new_abundance_col_titles = []
        reformatted_data = []
        for ftuple in data:
            tup = convert_fileidtoabundaceformat(ftuple, sanitize_str_for_dataframe_index(fileid_col_name),
                                                 abundance_col_titles[0])
            new_abundance_col_titles.extend(tup[0])
            reformatted_data.append(tup[1])
        abundance_col_titles = new_abundance_col_titles
        data = reformatted_data
    # Dicts to store the indices for the data generated by localizing the fragments and modifications
    modification_localization_col_titles: Dict[str, str] = dict()  # Dict containing {proteinID: column title}
    frag_localization_col_titles: Dict[str, str] = dict()  # Dict containing {proteinID: column title}

    # list that will contain the FileTuples after the fragments contained have been localized
    localized_data: List[FileTuple] = []  # contains the FileTuples once they have been localized against input proteins

    # Localization of fragments and modifications-----------------------------------------------------------------------
    # todo modify data in place instead of returning the modified copy?
    # todo use generator here instead of loop?
    for ftuple in data:
        # localizes each fragment within the proteins provided, either via master protein or via the protein fasta files
        # provided in the configuration
        if use_mod_in_master_prot:  # localize using the master protein positions and modifications
            file_headers_tuple: Tuple[FileTuple, Dict[str, str], Dict[str, str]] = \
                parse_masterlocalizations(ftuple, master_protein_fasta_id, mod_regex, master_regex)
        else:  # localize by aligning the fragment against a protein and looking at the modification index within the
            # fragment
            file_headers_tuple: Tuple[FileTuple, Dict[str, str], Dict[str, str]] = \
                parse_prot_localizations(ftuple, protein_seq_records, mod_regex)

        # add the data that has been localized to our list and make note of the DataFrame headers containing the
        # localization
        localized_data.append(file_headers_tuple[0])  # add the FileTuple to the list of localized FileTuples
        modification_localization_col_titles.update(file_headers_tuple[1])  # add the list of (proteinID, column
        # title) tuples
        frag_localization_col_titles.update(file_headers_tuple[2])  # Dict containing {proteinID: column title}
    # End of fragment and modification localization---------------------------------------------------------------------

    # Calculate the residue and modification abundances of each input against each desired protein----------------------
    residue_analysis_all_prot: List[Dict[Dict]] = []
    peptide_analysis_all_prot: List[Dict[Dict]] = []
    for ftuple in localized_data:
        # for residue modification analysis, calculate the amount each residue is modified
        residue_analysis_all_prot.append(calc_residue_mod_abundances(ftuple, modification_localization_col_titles,
                                                                     frag_localization_col_titles, abundance_col_titles,
                                                                     protein_seq_records))
        # for peptide modification analysis, calculate the amount each peptide fragment is modified
        if should_calculate_peptide_modifications:
            peptide_analysis_all_prot.append(calc_peptide_mod_abundances(ftuple, modification_localization_col_titles,
                                                                         frag_localization_col_titles,
                                                                         abundance_col_titles, protein_seq_records))
    # End of abundance calculations-------------------------------------------------------------------------------------

    # output the abundance data-----------------------------------------------------------------------------------------
    for prot_residue_analysis in residue_analysis_all_prot:
        for prot_id, sample_analysis in prot_residue_analysis.items():
            for file_id, abundance_array in sample_analysis.items():
                output_residue_analysis_data(prot_id, file_id, abundance_array, output_directory,
                                             residue_output_name_stub)

    for prot_peptide_analysis in peptide_analysis_all_prot:
        for file_id, prot_analysis in prot_peptide_analysis.items():
            for prot_id, fragment_list in prot_analysis.items():
                output_peptide_analysis_data(prot_id, file_id, fragment_list, output_directory,
                                             peptide_output_name_stub)
    # End of data output------------------------------------------------------------------------------------------------
    # End of program
    return


def gen_raw_sequences(ftuple: FileTuple) -> FileTuple:
    """
    Adds a column to the DataFrame containing a stripped down peptide without the cleavage annotations
    :param ftuple: The FileTuple to containing the FileData DataFrame to generate the raw sequence of each fragment
    :return: a FileTuple containing the fileID and a FileData DataFrame containing the raw sequence in the
    'stripped_sequence' column
    """
    file_data: pd.DataFrame = ftuple.FileData  # Extract the DataFrame
    file_data = file_data.assign(
        stripped_sequence=file_data['annotated_sequence'].apply(  # add a column that contains the raw
            lambda seq_str: seq_str[seq_str.find(".") + 1: seq_str.rfind(".")]))  # sequence to the DataFrame

    return FileTuple(ftuple.FileName, file_data)


def parse_masterlocalizations(ftuple: FileTuple, master_prot_fasta_id, mod_regex, pos_master_regex) -> Tuple[
    FileTuple, Dict[str, str], Dict[str, str]]:
    """
    Parses the modification and fragment localizations from a DataFrame using the positions in master and modifications
    in master proteins columns to obtain localization data instead of aligning the fragment to a given master protein
    :param pos_master_regex: the regex to use to parse out position in master from the 'position in master' column
    :param mod_regex: the regex to use to parse out the modifications from 'modifications in master proteins'
    :param ftuple:
    :param master_prot_fasta_id:
    :return: A tuple containing the FileTuple of localized data, a Dict mapping the proteinID to its modification \
    localizations in the DataFrame, and a Dict mapping proteinID's to their fragment localizations in the DataFrame
    """
    # NOTE: parses multiple master proteins, but as of now only the first is used
    # this provides support for non-localized PTM where only the amino acid is present and not the localization
    file_data: pd.DataFrame = ftuple.FileData
    localizations = []
    positions_in_master = []

    for row in file_data.itertuples():
        # Modification localization occurs here:------------------------------------------------------------------------
        mod_string = row.modifications_in_master_proteins
        # example mod_string "P10636-8 2xPhospho [S383; S]"
        # pandas seems to treat the items in the mod column as str, unless its not there and then its a float nan
        # force everything into string so we can make sure its not empty ("nan")
        if not str(mod_string) == "nan":
            matches = re.finditer(mod_regex, mod_string)
            # each group in the match_obj corresponds to a match for the capturing group [\d]{0,} (one or more digits)
            # and this gives us the index of the modification localization
            # NOTE: ONE INDEXED e.g. 1st amino acid=1
            localizations.append([int(mod_localization) for match_obj in matches
                                  for mod_localization in match_obj.groups() if mod_localization is not ''])
        else:
            localizations.append([])  # If it's nan there isn't a modification, indicate this as an empty list of mods
        # End of modification localization------------------------------------------------------------------------------

        # Fragment localization in protein occurs here------------------------------------------------------------------
        # sample pos_in_master_str: P10636-8 [355-377]
        pos_in_master_str = row.positions_in_master_proteins
        if not str(pos_in_master_str) == "nan":
            matches = re.finditer(pos_master_regex, pos_in_master_str)
            # want the first number (the start index of the fragment) and the second number,
            # so we only get capturing group 1 and capturing group 2
            # capturing group 0 is the whole match e.g. [355-377] and capturing group 2 is the second number e.g. 377
            # end of fragment is inclusive- end 377 includes aa 377
            positions_in_master.append([(int(match_obj.group(1)), int(match_obj.group(2)))
                                        for match_obj in matches])
        else:
            positions_in_master.append((-1))  # No position in master string
        # End of fragment localization----------------------------------------------------------------------------------

    # Add the columns containing the modification and fragment localization to the DataFrame
    file_data.insert(file_data.shape[1], "master_localized_mods", localizations)
    file_data.insert(file_data.shape[1], "master_frag_localization", positions_in_master)

    return FileTuple(ftuple.FileName, file_data), {master_prot_fasta_id: "master_localized_mods"}, \
           {master_prot_fasta_id: "master_frag_localization"}


def parse_prot_localizations(ftuple: FileTuple, protein_seq_records: Dict, mod_regex: str) -> \
        Tuple[FileTuple, Dict[str, str], Dict[str, str]]:
    """
    Parses out the localizations of the PTM by aligning each modified fragment to the protein sequences given in
    protein_seq_records, parsing out the modification index in each protein fragment, and using the fragment's index in
    the full protein as an offset to calculate the localization's index in the full protein.
    :param mod_regex: The regex string to use to parse out the modifications from the modifications column
    :param ftuple: a FileTuple with the data to localize
    :param protein_seq_records: the dict of proteinID mapped to its SequenceRecord
    :return: a Tuple containing the FileTuple with localization data, a Dict mapping the proteinID to its modification
    localizations in the DataFrame, and a Dict mapping proteinID's to their fragment localizations in the DataFrame
    """

    file_data: pd.DataFrame = ftuple.FileData
    mod_loc_column_titles = dict()  # maps Sequence Record ID to modification localization column name in DataFrame
    frag_loc_column_titles = dict()  # maps Sequence Record ID to fragment localization column name in DataFrame

    # iterate through all the input proteins to localize against
    for prot_id, protein in protein_seq_records.items():
        prot_mod_localizations = []
        positions_in_master = []  # master here is the protein currently being aligned against
        # the protein sequence to align against to find the fragment's location in the sequence
        protein_seq: str = protein.seq.upper()
        for row in file_data.itertuples():
            # Fragment localization occurs here-------------------------------------------------------------------------
            frag_index_in_prot = protein_seq.find(row.stripped_sequence)  # find the fragment's index in the protein
            # if the fragment is contained in the current protein
            if frag_index_in_prot != -1:
                # If the fragment is in the protein, add its localizations to the list
                positions_in_master.append([(frag_index_in_prot + 1, frag_index_in_prot + len(row.stripped_sequence))])
                # end of fragment localization--------------------------------------------------------------------------

                # PTM modification localization occurs here-------------------------------------------------------------
                mod_string = row.modifications
                if not str(mod_string) == "nan":
                    matches = re.finditer(mod_regex, mod_string)
                    prot_mod_localizations.append([int(mod_localization) + frag_index_in_prot for match_obj in matches
                                                   for mod_localization in match_obj.groups()
                                                   if mod_localization is not ''])
                else:
                    prot_mod_localizations.append([])  # if no modifications add the list containing no modifications
                # end of PTM/ modification localization-----------------------------------------------------------------

            else:
                prot_mod_localizations.append([frag_index_in_prot])  # if index is -1 the fragment isn't in this protein
                positions_in_master.append([(-1,)])  # indicate that the fragment isn't in this protein

        # clean up the protein ID so we can use it to index things in our DataFrames
        sanitized_protein_id = sanitize_str_for_dataframe_index(prot_id)

        prot_mod_column_title = sanitized_protein_id + "_mod_localization"
        frag_loc_column_title = sanitized_protein_id + "_fragment_localization"

        # Add the localizations to the DataFrames and add the column headers to out dictionaries so we can get these
        # columns later
        file_data.insert(file_data.shape[1], prot_mod_column_title, prot_mod_localizations)
        file_data.insert(file_data.shape[1], frag_loc_column_title, positions_in_master)
        mod_loc_column_titles.update({protein.id: prot_mod_column_title})
        frag_loc_column_titles.update({protein.id: frag_loc_column_title})

    return FileTuple(ftuple.FileName, file_data), mod_loc_column_titles, frag_loc_column_titles


def calc_residue_mod_abundances(ftuple, localization_col_titles: Dict, frag_localization_col_titles: Dict,
                                abundance_col_titles: List,
                                protein_seq_records: Dict):
    """
    Calculates, for a DataFrame of localized ptm data, the abundance of each residue and how much that resiude is
    modified.
    :param ftuple: FileTuple containing the file ID and the DataFrame with localized data
    :param localization_col_titles: dict mapping protein ID to the column containing the mod localization
    :param frag_localization_col_titles: dict mapping proteinID to the fragment localization column title
    :param abundance_col_titles: list of titles of the abundance columns of interest in the DataFrame
    :param protein_seq_records: dict containing the protein ID mapped to each SeqRecord
    :return: a dict mapping proteinIDs to their residue abundance arrays
    """
    fdata = ftuple.FileData
    all_prot_abundances: Dict[Dict] = {}  # a dict of each protein ID mapped a dict of column ids mapped to their
    # respective abundance arrays

    # There are three nested levels here- each master protein is being analyzed against
    # each abundance column fragment by fragment
    for proteinID, mod_column_title in localization_col_titles.items():
        protein_len = len(protein_seq_records[proteinID])  # Get the protein length so we know how big to make the
        # array we're storing the abundances in
        res_abundance_col_title = mod_column_title.replace('_mod_localization', '')
        all_prot_abundances[res_abundance_col_title] = {}
        for abundance_col_title in abundance_col_titles:
            abundance_col_title = sanitize_str_for_dataframe_index(abundance_col_title)
            # THIS IS ONE INDEXED. RESIDUE 1 IS IN INDEX 1 of the array. index 0 is UNUSED
            res_abundances = np.zeros((protein_len + 1, 2),
                                      dtype=float)  # col. 0= mod abundance, col. 1=residue abundance
            for row in fdata.iterrows():
                fragment = row[1]
                mod_localization = fragment[mod_column_title]
                frag_localization = fragment[frag_localization_col_titles[proteinID]]
                frag_abundance = fragment[abundance_col_title]

                # if the fragment is in the given protein
                if frag_localization[0][0] != -1:
                    # only uses the first localization
                    for i in range(frag_localization[0][0], frag_localization[0][1] + 1, 1):
                        # add the abundance to the abundance of each residue in the fragment
                        res_abundances[i][1] += frag_abundance
                    for mod in mod_localization:
                        # add the abundance to each modified residue contained in the fragment
                        res_abundances[mod][0] += frag_abundance
            assert (res_abundances[i][0] <= res_abundances[i][1] for i in range(0, len(res_abundances)))
            all_prot_abundances[res_abundance_col_title][abundance_col_title] = res_abundances

    return all_prot_abundances


def calc_peptide_mod_abundances(ftuple, mod_localization_col_titles, frag_localization_col_titles,
                                abundance_col_titles, protein_seqrecords):
    df = ftuple.FileData
    fdata = df.fillna(0)

    # group each peptide fragment by the sequence
    grouped = fdata.groupby('stripped_sequence')
    sample_frag_abundances = {}
    for abund_col_title in abundance_col_titles:
        abund_col_title = sanitize_str_for_dataframe_index(abund_col_title)
        sample_prot_frag_abundances = {}
        for prot_id in protein_seqrecords:
            prot_frag_abundances = []
            mod_col_title = mod_localization_col_titles[prot_id]
            frag_loc_col_title = frag_localization_col_titles[prot_id]
            for frags_same_seq in grouped:
                # a dd all the abundances for fragments with the same sequence
                frag_abundance = frags_same_seq[1][abund_col_title].sum()
                # ID all the fragments with modifications
                bools = []
                for mods in frags_same_seq[1][mod_col_title]:
                    if mods:
                        if -1 not in mods:
                            bools.append(True)
                        else:
                            bools.append(False)
                    else:
                        bools.append(False)
                # add the abundances for all fragments with modifications
                mod_abundance = frags_same_seq[1].loc[bools, abund_col_title].sum()
                assert (mod_abundance <= frag_abundance)
                frag_localization_tuple = frags_same_seq[1][frag_loc_col_title].iloc[0][0]
                if -1 in frag_localization_tuple:
                    prot_frag_abundances.append((frags_same_seq[0], -1, -1, mod_abundance,
                                                 frag_abundance))
                else:
                    prot_frag_abundances.append((frags_same_seq[0], frag_localization_tuple[0],
                                                 frag_localization_tuple[1], mod_abundance, frag_abundance))
            sample_prot_frag_abundances.update({prot_id: prot_frag_abundances})
        sample_frag_abundances.update({abund_col_title: sample_prot_frag_abundances})
    return sample_frag_abundances


def ingest_file_data(files: List[str]) -> List[FileTuple]:
    """
    Takes the list if files to ingest, reads them, and returns the data as
    a list of tuples of the file name and a DataFrame of the file contents
    :param files: a list of paths to input files
    :return: a list containing 2-tuples of the filename and a dataframe of the file contents
    """
    data = []
    # open each file
    for input_file_path in files:
        with open(input_file_path, mode='r') as infile:
            # read the contents into a DataFrame
            contents = pd.read_csv(infile, delimiter=',', skipinitialspace=True)
            # sanitize the headers only- no spaces, all lowercase, no parenthesis for easier indexing
            contents.columns = pd.Index([sanitize_str_for_dataframe_index(header) for header in contents.columns])
            # let the DataFrame guess at its data types so everything isn't a str or some other object
            contents.infer_objects()
        # Add the file data to the list with its filename as a FileTuple object
        data.append(FileTuple(infile, contents))

    return data


def sanitize_str_for_dataframe_index(dirty_string):
    # remove spaces, parenthesis, octothorpes so that it plays nicely as an index for DatFrames and Series objects
    return dirty_string.strip().lower().replace(' ', '_').replace('(', '').replace(')', '').replace("#", "num")


def get_protein_sequences(fasta_files: List[str]) -> Dict:
    """
    Ingests the proteins sequences from a list of fasta files
    :param fasta_files: the list of paths to fasta files to use in the alignment and localization
    :return: a Dict mapping sequenceIDs to Bio.SeqRecord objects
    """
    # The ID and the SeqRecord
    # somewhat redundant, as the SeqRecord already contains the ID in it
    # TODO convert from tuple to just the SeqRecord?
    protein_seq_records: Dict[str, SeqRecord] = dict()
    for file in fasta_files:
        with open(file, "r") as handle:
            for sequence_record in SeqIO.parse(handle, "fasta"):
                # add the SeqRecord to the Dict of SeqRecords
                protein_seq_records.update({sequence_record.id: sequence_record})

    return protein_seq_records


def output_residue_analysis_data(prot_id, fileid, abundance_array, output_directory, output_name_stub):
    filename = output_directory + fileid + prot_id + output_name_stub + ".csv"
    with open(filename, 'w') as outfile:
        writer = csv.writer(outfile)
        writer.writerow(["Residue #:", "Modification Abundance", "Residue Abundance", "Modification Proportion"])
        for i, arr in enumerate(abundance_array):
            if (arr[0] != float('NaN')) and (arr[1] != 0) and (arr[1] != float('NaN')):
                mod_prop = arr[0] / arr[1]
                writer.writerow([i, arr[0], arr[1], mod_prop])
            else:
                writer.writerow([i, arr[0], arr[1], float("nan")])
    return


def output_peptide_analysis_data(prot_id, file_id, fragment_list, output_directory, peptide_output_name_stub):
    filename = output_directory + file_id + prot_id + peptide_output_name_stub + ".csv"
    with open(filename, 'w') as outfile:
        writer = csv.writer(outfile)
        writer.writerow(["Fragment", "Start Position", "End Position", "Length", "Phosphorylation Abundance",
                         "Fragment Abundance", "Modification Proportion"])
        for i in fragment_list:
            phos_abundance = i[3]
            frag_abundance = i[4]
            if (phos_abundance != float('NaN')) and (frag_abundance != 0) and (frag_abundance != float('NaN')):
                mod_prop = phos_abundance / frag_abundance
                writer.writerow([i[0], i[1], i[2], i[3], i[4], mod_prop])
            else:
                writer.writerow([i[0], i[1], i[2], i[3], i[4], float("nan")])
    return


if __name__ == '__main__':
    # execute only if run as a script
    main()
