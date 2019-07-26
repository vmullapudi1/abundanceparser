from typing import List

import pandas as pd
import toml


def main():
    # Get the desired configuration
    config_file: str = "tests/testConfig.toml"
    configuration: dict = toml.load(config_file)
    input_files: List[str] = configuration['input']["input_files"]
    use_mod_in_master_prot: bool = configuration['parser_config']['master'][
        'use']

    # Internalize the file's data
    # input_data is a list of tuples (filename, pandas DataFrame of the csv)
    input_data: list = ingest_file_data(files=input_files)

    data = (gen_raw_sequences(file_tuple[1]) for file_tuple in input_data)
    # print(list(data))


def ingest_file_data(files: List[str]) -> List[tuple]:
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


def gen_raw_sequences(file_data: pd.DataFrame):
    """
    Adds a column to the DataFrame containing a stripped down peptide without
    the cleavage annotations
    """
    file_data = file_data.assign(
        stripped_sequence=file_data['Annotated Sequence'].apply(
            lambda seq_str: seq_str[seq_str.find(".") + 1:seq_str.rfind(".")]))
    print(file_data)


if __name__ == '__main__':
    # execute only if run as a script
    main()
