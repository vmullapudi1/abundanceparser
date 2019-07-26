import pandas as pd
import toml


def main():
    # Get the desired configuration
    config_file = "tests/testConfig.toml"
    configuration = toml.load(config_file)
    input_files = configuration['input']["input_files"]
    use_mod_in_master_proteins = configuration['parser_config']['master'][
        'use']

    # Internalize the file's data
    # input_data is a list of tuples (filename, pandas DataFrame of the csv)
    input_data = ingest_file_data(files=input_files)

    for file_tuple in input_data:
        format_sequence(file_tuple[1])


def ingest_file_data(files):
    """ Takes the list if files to ingest, reads them, and returns the data as a
    list of tuples of the file name and a DataFrame of the file contents
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


def format_sequence(file_data):
    file_data['Annotated Sequence'] = file_data['Annotated Sequence'] \
        .apply(
        lambda seq_str: seq_str[seq_str.find(".") + 1:seq_str.rfind(".")])



if __name__ == '__main__':
    # execute only if run as a script
    main()
