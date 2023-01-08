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
from collections import OrderedDict
from dataclasses import dataclass, field
import math
import numpy as np
import matplotlib.pyplot as plt
import statistics
from datetime import date
from datalite import datalite, fetch

from lbrsys import robot_id, mag_corrections, robot_calibrations
from lbrsys.settings import dbfile
from lbrsys.settings import LOG_DIR
from lbrsys.settings import MAG_CALIBRATION_DIR, magCalibrationLogFile

from lbrsys.robdrivers.ellipse_fit import fit_ellipse, get_ellipse_pts, cart_to_pol
from lbrsys.robdrivers.calibration import Calibration, CalibrationSetting

"""  todo - consider switching approach to use datalite
@datalite(db_path=dbfile)
@dataclass
class Mag_Calibration(object):
    robot_id: int = 0
    alpha: float = 0.0
    beta: float = 0.0
    t0: float = 0.0
    t1: float = 0.0
    t2: float = 0.0
    t3: float = 0.0

    def __post_init__(self):
        pass


def fetch_mag_calibration(self, robot_id):
    cal = None
    cals = fetch.fetch_if(Mag_Calibration, "robot_id == ?", (robot_id,))
    if len(cals) != 0:
        cal = cals[0]

    print(f"Fetched mag calibration for {robot_id}: {cal}")
    return cal
"""

@dataclass
class Ellipse_Model(object):
    """Hold and manage the coefficients and polar parameters for ellipse
        fitted from calibration data.
        Ellipse described by:  ax^2 + bxy + cy^2 + dx + ey + f = 0
    """
    a: float = 0.
    b: float = 0.
    c: float = 0.
    d: float = 0.
    e: float = 0.
    f: float = 0.
    x0: float = 0.
    y0: float = 0.
    ap: float = 0.
    bp: float = 0.
    ep: float = 0.
    phi: float = 0.


@dataclass(order=True)
class Magcal(object):
    raw_x: list[float] = field(default_factory=list)
    raw_y: list[float] = field(default_factory=list)
    show_enabled: bool = field(default=False)
    save_enabled: bool = field(default=True)

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
    plot_mgmt: OrderedDict = field(init=False, default_factory=OrderedDict)
    final_corrections: np.array = field(init=False, default=None)
    ellipse: Ellipse_Model = field(init=False, default=None)

    def __post_init__(self):
        # Configure Plots
        # matplotlib.use('Qt5Agg')
        # matplotlib.use('Agg')
        plt.style.use('seaborn-v0_8-whitegrid')
        figsize = (8, 8)
        xlabel = "uT"
        ylabel = "uT"
        x = self.raw_x
        y = self.raw_y
        xlim_min = min([min(x) * 1, abs(max(x)) * 2])
        xlim_max = max([min(x) * 1, abs(max(x)) * 2])
        ylim_min = min([min(y) * 1, abs(max(y)) * 1])
        ylim_max = max([min(y) * 1, abs(max(y)) * 1])

        self.plot_mgmt['raw'] = {'fig': 1, 'title': 'Raw Data'}
        self.plot_mgmt['hard_iron'] = {'fig': 2, 'title': 'Hard Iron Corrected'}
        self.plot_mgmt['corrected_1'] = {'fig': 3, 'title': 'Corrections 1'}
        self.plot_mgmt['corrected_2'] = {'fig': 4, 'title': 'Corrections 2'}
        self.plot_mgmt['composite'] = {'fig': 5, 'title': 'Composite'}
        self.plot_mgmt['backtest'] = {'fig': 6, 'title': 'Backtest'}

        keys = list(self.plot_mgmt.keys())
        for n in range(len(keys)):
            plt.figure(n+1, figsize=figsize)
            plt.title(self.plot_mgmt[keys[n]]['title'])
            plt.ylim(ylim_min, ylim_max)
            plt.xlim(xlim_min, xlim_max)
            plt.xlabel(xlabel)
            plt.ylabel(ylabel)
            ax = plt.gca()
            ax.axis('equal')

        plt.figure(1)


    def plot(self, x=None, y=None, fmt='.', *args, fig_name=None, **kwargs):
        fig_title = 'Calibration Analysis'  # default

        fig_item = self.plot_mgmt.get(fig_name, {'fig': 1, 'title': fig_title})
        fig = fig_item['fig']
        fig_title = fig_item['title']
        plt.figure(fig)
        plt.title(fig_title)

        if x is None:
            x = self.x
        if y is None:
            y = self.y

        ax = plt.gca()
        ax.plot(x, y, fmt, *args, **kwargs)

        return ax

    def show(self):
        if self.show_enabled:
            plt.show()

        return

    def save(self):
        if not self.save_enabled:
            return

        today = str(date.today())

        if not os.path.isdir(MAG_CALIBRATION_DIR):
            os.mkdir(MAG_CALIBRATION_DIR)

        for fig_item in self.plot_mgmt:
            fig_num = self.plot_mgmt[fig_item]['fig']
            image_file_name = f"{today}-mag-{fig_num}-{fig_item}.png"
            fig = plt.figure(fig_num)
            if fig.gca().lines:
                image_full_path = os.path.join(MAG_CALIBRATION_DIR, image_file_name)
                plt.savefig(image_full_path)

        mag_corr = mag_corrections(self.alpha, self.beta,
                                   self.final_corrections[0][0], self.final_corrections[0][1],
                                   self.final_corrections[1][0], self.final_corrections[1][1],
                                   )

        save_mag_corrections(mag_corr)

        return

    def close_figures(self):
        plt.close('all')

    def iron_corrections_orig_algorithm(self):
        self.plot(self.raw_x, self.raw_y, '.', fig_name='raw', color='cyan')

        tolerance = 0.001
        final_corrections = None

        self.alpha, self.beta, self.x, self.y = correct_hard_iron(self.raw_x, self.raw_y)
        print(f"alpha: {self.alpha}, beta: {self.beta}")

        corrected_ax = self.plot(self.x, self.y, '.', fig_name='hard_iron', color='blue')

        self.r_mag = [math.sqrt((x)**2 + (y)**2) for x, y in zip(self.x, self.y)]
        self.major_axis = max(self.r_mag)
        self.minor_axis = min(self.r_mag)
        print(f"Major axis: {self.major_axis}, Minor axis: {self.minor_axis}")
        assert self.major_axis != 0, f"Unexpected 0 major axis in iron_correction"

        if abs(self.major_axis - self.minor_axis) > tolerance:
            self.soft_iron = True

            final_corrections = self.soft_iron_by_ellipse()
            # final_corrections = self.soft_iron_by_rotation()

            self.save()
            self.show()
            self.close_figures()

        else:
            print("Soft iron correction not required")

        self.final_corrections = final_corrections

        return self.alpha, self.beta, self.final_corrections

    def iron_corrections(self):
        self.plot(self.raw_x, self.raw_y, '.', fig_name='raw', color='cyan')

        tolerance = 0.001
        self.final_corrections = None

        self.alpha, self.beta, self.x, self.y = correct_hard_iron(self.raw_x, self.raw_y)
        print(f"alpha: {self.alpha}, beta: {self.beta}")

        ax = self.plot(self.x, self.y, '.', fig_name='hard_iron', color='blue')
        
        # This method of determining axes is replaced by a best-fitting ellipse approach
        # self.r_mag = [math.sqrt((x)**2 + (y)**2) for x, y in zip(self.x, self.y)]
        # self.major_axis = max(self.r_mag)
        # self.minor_axis = min(self.r_mag)
        # print(f"Major axis: {self.major_axis}, Minor axis: {self.minor_axis}")
        # assert self.major_axis != 0, f"Unexpected 0 major axis in iron_correction"

        xa = np.array(self.x)
        ya = np.array(self.y)

        coeffs = fit_ellipse(xa, ya)

        print('Fitted ellipse parameters:')
        print('a, b, c, d, e, f =', coeffs)
        x0, y0, ap, bp, e, phi = cart_to_pol(coeffs)
        radius = bp
        print('x0, y0, ap, bp, e, phi = ', x0, y0, ap, bp, e, phi)

        self.ellipse = Ellipse_Model(*coeffs, x0, y0, ap, bp, e, phi)

        # add the fitted ellipse onto the plot
        xp, yp = get_ellipse_pts((x0, y0, ap, bp, e, phi))
        ax.plot(xp, yp, '+-', color='red')
        
        self.major_axis = self.ellipse.ap
        self.minor_axis = self.ellipse.bp

        if abs(self.major_axis - self.minor_axis) > tolerance:
            self.soft_iron = True

            # rotate the ellipse to align with x axis
            rotation = np.array([[math.cos(phi), math.sin(phi)],
                                 [-math.sin(phi), math.cos(phi)]])

            rotated = rotation @ np.array([self.x, self.y])

            ax = self.plot(rotated[0], rotated[1], '.', fig_name='composite', color='cyan')
            # plot the unrotated date and fitted ellipse for reference
            ax.plot(self.x, self.y, '.',  color='blue')
            ax.plot(xp, yp, '+-', color='red')

            # compress the ellipse into a circle
            sigma = self.minor_axis / self.major_axis
            print(f"sigma: {sigma}")
            x_circle = sigma * rotated[0]
            ax.plot(x_circle, rotated[1], '.', color='green')

            # rotate the compressed ellipse back into its original angle
            phi_neg = -phi
            re_rotation = np.array([[math.cos(phi_neg), math.sin(phi_neg)],
                                    [-math.sin(phi_neg), math.cos(phi_neg)]])

            orig_rotation = re_rotation @ np.array([x_circle, rotated[1]])
            self.plot(orig_rotation[0], orig_rotation[1], '+', fig_name='corrected_2', color='green')

            # calculate composite transformation matrix
            squish = np.array([[sigma, 0.], [0., 1.]])
            self.final_corrections = re_rotation @ squish @ rotation  # MUST be last first

            if self.backtest():
                print("Calibration model verified.\n")
            else:
                print("Calibration model failed.\n")

            self.save()
            self.show()
            self.close_figures()
        else:
            print("Soft iron correction not required") 

        return self.alpha, self.beta, self.final_corrections

    def backtest(self):
        print("\nBacktesting the raw data with the final corrections.")

        x_bt = np.array([x-self.alpha for x in self.raw_x])
        y_bt = np.array([y-self.beta for y in self.raw_y])

        bt_corrected = self.final_corrections @ np.array([x_bt, y_bt])

        self.plot(bt_corrected[0], bt_corrected[1], '.', fig_name='backtest')

        print("\tChecking circle for backtested results by fitting ellipse.")
        coeffs = fit_ellipse(bt_corrected[0], bt_corrected[1])
        x0, y0, ap, bp, e, phi = cart_to_pol(coeffs)
        print('\tx0, y0, ap, bp, e, phi = ', x0, y0, ap, bp, e, phi)
        sigma = round(bp, 3) / round(ap, 3)
        if abs(1 - sigma) <= 0.001:
            result = "passed"
        else:
            result = "failed"

        print(f"Backtest {result} with axis ratio {sigma}.\n")

        limit = 8./ap
        print(f"Checking symmetry of corrected data against radial range limit of {limit*100:.2f}%.")
        r_mag = [math.sqrt(x**2 + y**2) for x, y in zip(bt_corrected[0], bt_corrected[1])]
        r_mag_min = min(r_mag)
        r_mag_max = max(r_mag)
        mag_spread = 1 - r_mag_min / r_mag_max
        if mag_spread <= limit:
            result = "passed"
        else:
            result = "failed"

        print(f"Radial magnitude ranges from {r_mag_min:.3f} to {r_mag_max:.3f} uT.")
        print(f"Backtest {result} with radial magnitude spread of {round(mag_spread*100, 2)}%.\n")

        return True if result == "passed" else False


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

def get_mag_corrections():
    mc = None
    mag_corrs = []
    for c in ['MAG_ALPHA', 'MAG_BETA', 'MAG_COR0', 'MAG_COR1', 'MAG_COR2', 'MAG_COR3']:
        corr, corr_setting = robot_calibrations.find_setting(c)
        if corr_setting is not None:
            mag_corrs.append(corr)
        else:
            mag_corrs.append(0.0)

    return mag_corrections(mag_corrs[0], mag_corrs[1],
                           mag_corrs[2], mag_corrs[3],
                           mag_corrs[4], mag_corrs[5],
                           )


def save_mag_corrections(new_corrections):
    i = 0
    for c in ['MAG_ALPHA', 'MAG_BETA', 'MAG_COR0', 'MAG_COR1', 'MAG_COR2', 'MAG_COR3']:
        corr, corr_setting = robot_calibrations.find_setting(c)
        if corr_setting is not None:
            corr_setting.value = new_corrections[i]
            corr_setting.save()
        else:
            s = CalibrationSetting(robot_id, c, new_corrections[i])
            s.save()
        i += 1

    # reload calibrations
    robot_calibrations.update()  # todo find strategy to make thread safe (not yet an issue as of Jan, 2023)

    return


if __name__ == '__main__':
    # matplotlib.use('Qt5Agg')
    # matplotlib.use('Agg')
    # calc_mag_correction(data_file='/home/robot/lbr/logs/magCalibration.csv')
    # x, y = get_records('/home/robot/lbr/logs/mag_working/magCalibration.csv')
    x, y = get_records('/home/robot/lbr/logs/magCalibration-2023-01-01-raw.csv')
    # x, y = get_records(magCalibrationLogFile.format(today=str(date.today()))) # this only works for today's files

    mc = Magcal(x, y)
    print(get_mag_corrections())
    print(mc.iron_corrections())
    print(get_mag_corrections())

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
