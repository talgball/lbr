"""
magcal.py - Module to process calibration data for InvenSense MPU9150 and calculate
    corrections and factors to apply to future readings to get calibrated results.
    Currently, the "hard iron" adjustments of alpha and beta are supported, which are
    the offsets that are applied to new readings to center them on the origin and
    correct for any fixed magnetic field influences in the robot.
"""

__author__ = "Tal G. Ball"
__copyright__ = "Copyright (C) 2021 Tal G. Ball"
__license__ = "Apache License, Version 2.0"
__version__ = "1.0"

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.



import os
import matplotlib.pyplot as plt
import statistics
from datetime import date

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


def outliers(data, tolerance=2):
    sigma = statistics.stdev(data)
    mean = statistics.mean(data)
    boundary = tolerance * sigma
    print("Data mean: %.5f, standard deviation: %.5f" % (mean, sigma))
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
    all_outliers.sort(reverse=True) # required so that we're always deleting from the end
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
    alpha = round(((x_min + x_max) / 2.), 5)
    beta = round(((y_min + y_max) / 2.), 5)

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
    # plt.show()


def calc_mag_correction(x=None, y=None, data_file=None, base_plot_name='mag'):
    today = str(date.today())
    raw_fname = base_plot_name + "raw-" + today + '.png'
    corrected_fname = base_plot_name + "corrected-" + today + '.png'
    raw_image = os.path.join(LOG_DIR, raw_fname)
    corrected_image = os.path.join(LOG_DIR, corrected_fname)

    if x is None or y is None:
        if data_file is None:
            data_file = magCalibrationLogFile
        x, y = get_records(data_file)

    make_plot(x, y, "Magnetometer - Uncorrected", raw_image)
    alpha, beta, xc, yc = correct_hard_iron(x, y)
    print("alpha = %.5f, beta = %.5f" % (alpha, beta))
    make_plot(xc, yc, "Magnetometer - Corrected", corrected_image)

    return alpha, beta, xc, yc


if __name__ == '__main__':
    calc_mag_correction()