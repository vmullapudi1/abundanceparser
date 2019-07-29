from typing import List
from Bio import SeqIO, SeqRecord
import pandas as pd
import toml

# Path to configuration toml file
config_file:str = "tests/testConfig.toml"

def main():
    # Get the desired configuration
    configuration: dict = toml.load(config_file)
    input_files: List[str] = configuration['input']["input_files"]
    use_mod_in_master_prot: bool = configuration['parser_config']['master']['use']
    protein_fasta_files: List[str] = configuration['input']['prot_seq_fasta']
    # Internalize the file's data
    # input_data is a list of tuples (filename, pandas DataFrame of the csv)
    input_data: list = ingestfiledata(files=input_files)
    protein_seqrecords=getproteinsequences(protein_fasta_files)
    data = (genrawsequences(file_tuple) for file_tuple in input_data)

    # if use_mod_in_master_prot:
    #     localizeddata=(parsemasterlocalizations(file_tuple) for file_tuple in data)
    # else:
    #     localizeddata=parse


def ingestfiledata(files: List[str]) -> List[tuple]:
    """ Takes the list if files to ingest, reads them, and returns the data as
    a list of tuples of the file name and a DataFrame of the file contents
    """
    data = []
    for input_file_path in files:
        with open(input_file_path, mode='r') as infile:
            contents = pd.read_csv(infile,
                                   delimiter=',',
                                   skipinitialspace=True)
            contents.infer_objects()
        data.append((infile, contents))
    return data


def getproteinsequences(fasta_files:List[str]) -> List[SeqRecord]:
    protein_seqrecords: List[SeqRecord]=[]
    for file in fasta_files:
        with open(file, "rU") as handle:
            for record in SeqIO.parse(handle, "fasta"):
                protein_seqrecords.append(record)
    return protein_seqrecords


def genrawsequences(file_tuple):
    """
    Adds a column to the DataFrame containing a stripped down peptide without
    the cleavage annotations
    """
    file_data: pd.DataFrame = file_tuple[1]
    file_data = file_data.assign(
        stripped_sequence=file_data['Annotated Sequence'].apply(
            lambda seq_str: seq_str[seq_str.find(".") + 1:seq_str.rfind(".")]))
    return file_tuple[0], file_data


def parsemasterlocalizations(filedf):
    return


if __name__ == '__main__':
    # execute only if run as a script
    main()
