"""
magcal.py - Module to process calibration data for InvenSense MPU9150 and calculate
    corrections and factors to apply to future readings to get calibrated results.
    Currently, the "hard iron" adjustments of alpha and beta are supported, which are
    the offsets that are applied to new readings to center them on the origin and
    correct for any fixed magnetic field influences in the robot.

    ACTIVE DEVELOPMENT is underway in this module to implement soft iron corrections.
        Might not be in a working state for any individual commit.
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
from dataclasses import dataclass, field
import math
import numpy as np
import matplotlib.pyplot as plt
import statistics
from datetime import date

from lbrsys.settings import LOG_DIR
from lbrsys.settings import magCalibrationLogFile

from lbrsys.robdrivers.ellipse_fit import fit_ellipse, get_ellipse_pts, cart_to_pol


@dataclass(order=True)
class Magcal(object):
    raw_x: list[float] = field(default_factory=list)
    raw_y: list[float] = field(default_factory=list)

    x: list[float] = field(init=False, default_factory=list)
    y: list[float] = field(init=False, default_factory=list)
    r_mag: list[float] = field(init=False, default_factory=list)

    alpha: float = field(init=False, default=0.)
    beta: float = field(init=False, default=0.)
    major_axis: float = field(init=False, default=0.)
    minor_axis: float = field(init=False, default=0.)
    axis_index: int = field(init=False, default=-1)
    theta: float = field(init=False, default=0.)
    soft_iron: bool = field(init=False, default=False)
    final_corrections: np.array = field(init=False, default=None)
    plot_mgmt: dict = field(init=False, default_factory=dict)

    def __post_init__(self):
        # matplotlib.use('Qt5Agg')
        # matplotlib.use('Agg')
        plt.style.use('seaborn-v0_8-whitegrid')
        plt.figure(figsize=(8, 8))

        fig, ax = plt.subplots(nrows=5, ncols=1, figsize=(8, 40))
        # raw, hard iron, corrected-1, corrected-2, composite
        self.plot_mgmt['raw'] = {'ax': ax[0], 'title': 'Raw Data'}
        self.plot_mgmt['hard_iron'] = {'ax': ax[1], 'title': 'Hard Iron Corrected'}
        self.plot_mgmt['corrected_1'] = {'ax': ax[2], 'title': 'Corrections 1'}
        self.plot_mgmt['corrected_2'] = {'ax': ax[3], 'title': 'Corrections 2'}
        self.plot_mgmt['composite'] = {'ax': ax[4], 'title': 'Composite'}

        # ax[0, 0].plot(x, y, label='a')  # example

        x = self.raw_x
        y = self.raw_y
        xlim_min = min([min(x) * 2, abs(max(x)) * 2])
        xlim_max = max([min(x) * 2, abs(max(x)) * 2])
        ylim_min = min([min(y) * 2, abs(max(y)) * 2])
        ylim_max = max([min(y) * 2, abs(max(y)) * 2])

        graph_min = min(xlim_min, ylim_min)
        graph_max = max(xlim_max, ylim_max)
        plt.ylim(graph_min, ylim_max)
        plt.xlim(graph_min, graph_max)

    def plot(self, x=None, y=None, ax_name=None, title=None, **kwargs):
        ax_title = 'Calibration Analysis'  # default
        ax_item = self.plot_mgmt.get(ax_name, {'ax': plt.gca(), 'title': ax_title})
        ax = ax_item['ax']
        ax_title = ax_item['title']

        ax.set_box_aspect(1)

        if title is not None:   # title overrides ax_title
            plt.title(title)
            # fig = plt.gcf()
            # fig.set_label(title)
        else:
            plt.title(ax_title)

        if x is None:
            x = self.x
        if y is None:
            y = self.y

        ax.plot(x, y, **kwargs)

        return ax

    def iron_corrections(self):
        # make_plot(self.raw_x, self.raw_y, "Raw Data")
        self.plot(self.raw_x, self.raw_y, ax_name='raw', title="Raw Data")

        tolerance = 0.001
        final_corrections = None

        self.alpha, self.beta, self.x, self.y = correct_hard_iron(self.raw_x, self.raw_y)
        print(f"alpha: {self.alpha}, beta: {self.beta}")
        # make_plot(self.x, self.y, "Hard Iron")

        corrected_ax = self.plot(ax_name='hard_iron', title="Hard Iron Corrected")

        self.r_mag = [math.sqrt((x)**2 + (y)**2) for x, y in zip(self.x, self.y)]
        self.major_axis = max(self.r_mag)
        self.minor_axis = min(self.r_mag)
        print(f"Major axis: {self.major_axis}, Minor axis: {self.minor_axis}")
        assert self.major_axis != 0, f"Unexpected 0 major axis in iron_correction"

        if abs(self.major_axis - self.minor_axis) > tolerance:
            self.soft_iron = True

            # final_corrections = self.soft_iron_by_rotation()
            final_corrections = self.soft_iron_by_ellipse(ax=corrected_ax)

        else:
            print("Soft iron correction not required") 

        self.final_corrections = final_corrections

        return self.alpha, self.beta, self.final_corrections

    def soft_iron_by_ellipse(self, ax=None):
        """Use alternate method for soft iron correction consisting of fitting an ellipse
        to the calibration data and then using a circle based on the minor axis to correct the
        data.  Assumes Hard Iron correction has already been performed.
        """

        # plt.plot(self.x, self.y, '.', color='blue')
        xa = np.array(self.x)
        ya = np.array(self.y)

        coeffs = fit_ellipse(xa, ya)

        print('Fitted ellipse parameters:')
        print('a, b, c, d, e, f =', coeffs)
        x0, y0, ap, bp, e, phi = cart_to_pol(coeffs)
        radius = bp
        print('x0, y0, ap, bp, e, phi = ', x0, y0, ap, bp, e, phi)

        # add the fitted ellipse onto the plot
        xp, yp = get_ellipse_pts((x0, y0, ap, bp, e, phi))
        # plt.plot(xp, yp, '+-', color='red')
        self.plot(xp, yp, ax_name="corrected_1", title="Fitted Ellipse", color="red")

        # use the get_ellipse_pts function to draw circle using minor ellipse axis
        xc, yc = get_ellipse_pts((x0, y0, bp, bp, e, phi))
        # plt.plot(xc, yc, '-', color='black')
        self.plot(xc, yc, ax_name="corrected_1", color="black")

        # copy the data points onto the circle
        x_onc = []
        y_onc = []
        for xi, yi in zip(x, y):
            a = math.atan2(yi, xi)
            x_onc.append(bp * np.cos(a))
            y_onc.append(bp * np.sin(a))

        # plt.plot(x_onc, y_onc, '+', color='green')
        self.plot(x_onc, y_onc, ax_name="composite", title="Final Result")

        plt.show()

        return radius

    def soft_iron_by_rotation(self):
        self.axis_index = self.r_mag.index(self.major_axis)
        self.theta = math.asin(abs(self.y[self.axis_index]) / self.r_mag[self.axis_index])
        print(f"theta: {self.theta}")

        rotation = np.array([[math.cos(self.theta), math.sin(self.theta)],
                             [-math.sin(self.theta), math.cos(self.theta)]])

        rotated = rotation @ np.array([self.x, self.y])
        # make_plot(rotated[0], rotated[1], "Hard Iron Corrected and Rotated for x Alignment")
        self.plot(rotated[0], rotated[1], ax_name='hard_iron')
        sigma = self.minor_axis / self.major_axis
        print(f"sigma: {sigma}")
        x_circle = sigma * rotated[0]
        # make_plot(x_circle, rotated[1], "Rotated and Circled")
        self.plot(x_circle, rotated[1], ax_name="corrected_1", title="Rotated and Circled")

        tneg = -self.theta
        re_rotation = np.array([[math.cos(tneg), math.sin(tneg)],
                                [-math.sin(tneg), math.cos(tneg)]])

        orig_rotation = re_rotation @ np.array([x_circle, rotated[1]])

        # make_plot(orig_rotation[0], orig_rotation[1], "Final Result")
        self.plot(orig_rotation[0], orig_rotation[1], ax_name="corrected_2", title="Final Result")

        self.final_corrections = rotation @ np.array([[sigma, 0.], [0., 1.]]) @ re_rotation

        return self.final_corrections


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
    all_outliers.sort(reverse=True)  # required so that we're always deleting from the end
    deleted = []

    for i in all_outliers:
        print(f"Deleting outlier: ({x[i]}, {y[i]})")
        del x[i]
        del y[i]
        deleted.append(i)

    if len(deleted) != 0:
        print(f"Indexes deleted: {str(deleted)} as outliers.")
    else:
        print("No outliers detected.")

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


def make_plot(x, y, title="Sensor Data", image_file=None,
              xlabel='x uT', ylabel='y uT'):

    plt.style.use('seaborn-v0_8-whitegrid')
    plt.figure(figsize=(8, 8))

    # xi = list(range(len(x)))
    xlim_min = min([min(x)*2, abs(max(x))*2])
    xlim_max = max([min(x)*2, abs(max(x))*2])
    ylim_min = min([min(y)*2, abs(max(y))*2])
    ylim_max = max([min(y)*2, abs(max(y))*2])

    plt.ylim(ylim_min, ylim_max)
    plt.xlim(xlim_min, xlim_max)
    # fig1, ax = plt.subplots()
    # ax.set_box_aspect(1)

    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    # plt.xticks(xi, x)
    plt.title(title)
    # plt.legend()
    plt.plot(x, y, '.', color='blue')

    if image_file is not None:
        # fig = plt.gcf()
        plt.savefig(image_file)

    # plt.ioff()
    plt.show()

    # This fails and generates:
    #   "UserWarning: Starting a Matplotlib GUI outside of the main thread will likely fail.
    # plot_thread = Thread(target=plt.show, daemon=True)
    # plot_thread.start()


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
    # matplotlib.use('Qt5Agg')
    # matplotlib.use('Agg')
    # calc_mag_correction(data_file='/home/robot/lbr/logs/magCalibration.csv')
    # x, y = get_records('/home/robot/lbr/logs/mag_working/magCalibration.csv')
    x, y = get_records('/home/robot/lbr/logs/magCalibration-2023-01-01-raw.csv')

    mc = Magcal(x, y)
    print(mc.iron_corrections())

    """
    hix = -34.35
    hiy = 8.85
    corrections = np.array([[0.39592896, 0.48238524], [-0.48238524, 0.83330418]])

    xc = []
    yc = []

    for xi, yi in zip(x, y):
        hadj = [xi - hix, yi - hiy, -25.]
        hadj_soft = corrections @ np.array([[hadj[0]], [hadj[1]]])
        hadj = list([hadj_soft[0][0], hadj_soft[1][0], hadj[2]])
        xc.append(hadj[0])
        yc.append(hadj[1])
        


    make_plot(xc, yc, "Corrected - directly")
    """
