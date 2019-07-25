import csv

import toml


def main():
    config_file = "data/tests/testConfig.toml"
    configuration = toml.load(config_file)
    input_files = configuration['input']["input_files"]
    analyze_files(input_files)


def analyze_files(files, config):
    for input_file_path in files:
        with open(input_file_path, mode='r') as infile:
            file_reader = csv.DictReader(infile,
                                         delimiter=',',
                                         skipinitialspace=True,
                                         strict=True)
            headers = file_reader.fieldnames
            print(headers)
            for row in file_reader:
                print(row)


if __name__ == '__main__':
    # execute only if run as a script
    main()
