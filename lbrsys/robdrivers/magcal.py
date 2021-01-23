
import os
import matplotlib.pyplot as plt
import statistics

from lbrsys.settings import LOG_DIR
from lbrsys.settings import magCalibrationLogFile

def get_records(path):
    with open(path, 'r') as f:
        records = f.readlines()

    print(f"Record Count: {len(records)}")
    x = []
    y = []

    for r in records[1:]:
        fields = r.strip('\n').split(',')
        x.append(float(fields[0]))
        y.append(float(fields[1]))

    return x, y


def outliers(data, tolerance=3):
    sigma = statistics.stdev(data)
    mean = statistics.mean(data)
    boundary = tolerance * sigma
    out_index = []
    i = 0
    for d in data:
        distance = abs(d - mean)
        if distance > boundary:
            out_index.append(i)
        i += 1
    return out_index


def remove_outliers(x, y):
    x_outliers = outliers(x)
    y_outliers = outliers(y)
    all_outliers = list(set(x_outliers) | set(y_outliers))
    deleted = []

    for i in all_outliers:
        print(f"Deleting outlier: ({x[i]}, {y[i]})")
        del x[i]
        del y[i]
        deleted.append(i)

    print(f"Indexes deleted: {str(deleted)}")
    return deleted


def correct_hard_iron(x, y):
    removed = remove_outliers(x, y)
    n = len(removed)
    if n > 0:
        if n > 1:
            noun = "outliers"
        else:
            noun = "outlier"
        print(f"Removed {n} {noun}")

    x_min = min(x)
    x_max = max(x)
    y_min = min(y)
    y_max = max(y)
    alpha = (x_min + x_max) / 2.
    beta = (y_min + y_max) / 2.

    assert len(x) == len(y), "x and y require equal lengths"

    x_corrected = []
    y_corrected = []
    for i in range(len(x)):
        x_corrected.append(x[i] - alpha)
        y_corrected.append(y[i] - beta)

    return alpha, beta, x_corrected, y_corrected


def make_plot(x, y, title="Sensor Data", image_file="sensor.png",
              xlabel='x uT', ylabel='y uT'):

    plt.style.use('seaborn-whitegrid')
    # xi = list(range(len(x)))
    xlim_min = min([min(x)*2, abs(max(x))*2])
    xlim_max = max([min(x)*2, abs(max(x))*2])
    ylim_min = min([min(y)*2, abs(max(y))*2])
    ylim_max = max([min(y)*2, abs(max(y))*2])

    plt.ylim(ylim_min, ylim_max)
    plt.xlim(xlim_min, xlim_max)

    plt.figure(figsize=(8, 6))
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    # plt.xticks(xi, x)
    plt.title(title)
    #plt.legend()
    plt.plot(x, y, '.', color='blue')
    # fig = plt.gcf()
    plt.savefig(image_file)
    plt.show()
    # fig.savefig("test2.png")


def main():
    raw_image = os.path.join(LOG_DIR, 'magraw.png')
    corrected_image = os.path.join(LOG_DIR, 'magcorrected.png')
    x, y = get_records(magCalibrationLogFile)
    make_plot(x, y, "Magnetometer - Uncorrected", raw_image)
    alpha, beta, xc, yc = correct_hard_iron(x, y)
    print("alpha = %.5f, beta = %.5f" % (alpha, beta))
    make_plot(xc, yc, "Magnetometer - Corrected", corrected_image)


if __name__ == '__main__':
    main()