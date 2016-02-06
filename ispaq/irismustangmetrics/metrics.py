#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Python module containing wrappers for the IRISMustangMetrics R package.
:copyright:
    Mazama Science
:license:
    GNU Lesser General Public License, Version 3
    (http://www.gnu.org/copyleft/lesser.html)
    
Metrics from the IRISMustangMetrics package fall into several categories
depending on the following factors:

* whether special *business logic* is required to identify appropriate data
* number of r_stream objects passed in (1 or 2)
* return type (single values, multilpe values, times, spectra, *etc.*)

Functions in the IRISMustangMetrics R package provide this metadata so that
functions can be called programmatically from python without the user having
to know anything about the particular metric function they are calling.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
from future.builtins import *  # NOQA


### ----------------------------------------------------------------------------


from obspy.core import UTCDateTime

from ispaq.irisseismic.webservices import R_getSNCL

import pandas as pd

# Connect to R through the rpy2 module
from rpy2.robjects import r, pandas2ri

# R options
r('options(digits.secs=6)')      # print out fractional seconds


###   R functions called internally     ----------------------------------------


# NOTE:  These functions behave exactly the same as the R versions and require
# NOTE:  R-compatible objects as arguments.

# IRISMustangMetrics helper functions
_R_metricList2DF = r('IRISMustangMetrics::metricList2DF')
_R_metricList2Xml = r('IRISMustangMetrics::metricList2Xml')

def _R_getMetricMetadata():
    """
    This function should probably return a python dictionary with the following
    information:
     * name -- char
     * streamCount -- int, (number of streams on input)
     * fullDay -- logical
     * outputType -- char, [SingleValue | MultipleValue | MultipleTime | Spectrum | Other?]
     * speed -- char, [slow | medium | fast] (set basic expecations)
     * extraAttributes -- char, (comma separated list of extra attributes returned in DF)
     * businessLogic -- char, (Description of business logic which should be implmented in python.)
    """
    # TODO:  Replace this functionalitiy with IRISMustangMetrics::getMetricMetadata
    functionDict = {'basicStats':{'streamCount':1,'outputType':'SingleValue','fullDay':True,'speed':'fast','extraAttributes':None,'businessLogic':None},
                    'gaps':{'streamCount':1,'outputType':'SingleValue','fullDay':True,'speed':'fast','extraAttributes':None,'businessLogic':None},
                    'stateOfHealth':{'streamCount':1,'outputType':'SingleValue','fullDay':True,'speed':'fast','extraAttributes':None,'businessLogic':None},
                    'STALTA':{'streamCount':1,'outputType':'SingleValue','fullDay':True,'speed':'slow','extraAttributes':None,'businessLogic':'Limit to BH and HH channels.'},
                    'spikes':{'streamCount':1,'outputType':'SingleValue','fullDay':True,'speed':'fast','extraAttributes':None,'businessLogic':None}}
    return(functionDict)

###   R functions still to be written     --------------------------------------


def listMetricFunctions(functionType="simple"):
    """
    Function to be added to the IRISMustangMetrics package.
    
    "simple" metrics are those that require only a single stream as input and
    return a metricList of SingleValueMetrics as output. They may may have
    additional arguments which can be used but the provided defaults are 
    typically adequate.

    """
    df = pd.DataFrame.from_dict(_R_getMetricMetadata(), orient='index')
    names = df.index.tolist()
    
    
    functionList = _R_getMetricMetadata().keys()
    
    return(functionList)


def simpleMetricsOutput(df, path):
    sigfigs = 6
    # TODO actually finish this thing
    # Look up how to calculate sigfigs using numpy or pandas
    df.to_csv(path)
    
    
 

###   Functions for SingleValueMetrics     -------------------------------------


def applyMetric(r_stream, metricName):
    function = 'IRISMustangMetrics::' + metricName + 'Metric'
    R_function = r(function)
    try:
        r_metricList = R_function(r_stream)
    except Error as e:
        print(e)
    r_dataframe = _R_metricList2DF(r_metricList)
    df = pandas2ri.ri2py(r_dataframe)
    # TODO:  How to automatically convert times
    starttime = []
    for i in df.starttime.tolist():
        starttime.append(UTCDateTime(i))
    df.starttime = starttime
    endtime = []
    for i in df.endtime.tolist():
        endtime.append(UTCDateTime(i))
    df.endtime = endtime
    return df


### ----------------------------------------------------------------------------


if __name__ == '__main__':
    import doctest
    doctest.testmod(exclude_empty=True)
