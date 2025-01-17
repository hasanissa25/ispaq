"""
ISPAQ Business Logic for Orientation Check Metrics.

:copyright:
    Mazama Science
:license:
    GNU Lesser General Public License, Version 3
    (http://www.gnu.org/copyleft/lesser.html)
"""

from __future__ import (absolute_import, division, print_function)

import numpy as np
import pandas as pd

from .concierge import NoAvailableDataError

from . import utils
from . import irisseismic
from . import irismustangmetrics

from obspy import UTCDateTime
from rpy2.robjects import pandas2ri
import rpy2.robjects as ro
from rpy2.robjects import numpy2ri


def orientationCheck_metrics(concierge):
    """
    Generate *orientationCheck* metrics.

    :type concierge: :class:`~ispaq.concierge.Concierge`
    :param concierge: Data access expiditer.
    
    :rtype: pandas dataframe
    :return: Dataframe of simple metrics.

    .. rubric:: Example

    TODO:  doctest examples
    """
    # Get the logger from the concierge
    logger = concierge.logger
        
    # Default parameters from IRISMustangUtils::generateMetrics_orientationCheck
    channelFilter = "[BCHLM][HX]."    
    logger.debug("channelFilter %s" % channelFilter)
    minmag = 7.0
    maxdepth = 100
    eventMinradius = 0
    eventMaxradius = 180
    windowSecsBefore = 20
    windowSecsAfter = 600
    taper = 0.05
    filterArgs = [2,0.02,0.04]    
    degreeIncrement = 1
        
    # Sanity check for metadata
    if concierge.station_url is None:
        logger.warning('No station metadata found for orientationCheck metrics')
        return None


    # Create an initial availability that includes everything for the entire span
    start = concierge.requested_starttime
    end = concierge.requested_endtime
    if concierge.station_client is None:
        try:
            initialAvailability = concierge.get_availability("orientation", starttime=start, endtime=end)
        except NoAvailableDataError as e:
            raise
        except Exception as e:
            logger.error("concierge.get_availability() failed: '%s'" % e)
            return None

    # Get the seismic events in this time period
    events = concierge.get_event(minmag=minmag)
        
    # Sanity check
    if events is None or events.shape[0] == 0:
        logger.info('No events found for orientationCheck metrics.')
        return None
        
    # Container for all of the metrics dataframes generated
    dataframes = []

    #############################################################
    ## Loop through each event.
    #############################################################

    logger.info('Calculating orientationCheck metrics for %d events' % events.shape[0])


    for (index, event) in events.iterrows():

        logger.info('Magnitude %3.1f event: %s %sT%s:%s:%sZ' % (event.magnitude, event.eventLocationName, event.time.date, str(event.time.hour).zfill(2), str(event.time.minute).zfill(2), str(event.time.second).zfill(2)))
        
        # Sanity check
        if pd.isnull(event.latitude) or pd.isnull(event.longitude):
            logger.info('Skipping event because of missing longitude or latitude')
            continue
    
        # Sanity check
        if pd.isnull(event.depth):
            logger.info('Skipping event because of missing depth')
            continue        
        
        # Get the data availability around this event
        # NOTE:  Get availability from 2 minutes before event until 28 minutes after
        # Get the data availability using spatial search parameters
        halfHourStart = event.time - 60 * 2
        halfHourEnd = event.time + 60 * 28

        logger.debug("Looking for metadata from %s to %s" % (halfHourStart.strftime("%Y-%m-%dT%H:%M:%S"),halfHourEnd.strftime("%Y-%m-%dT%H:%M:%S")))

        # crossCorrelation requires 3 channels, look for all 3 even if input SNCL pattern is for one (i.e., TA.109..BHZ will look for TA.109C..BH?)
        original_sncl_patterns = concierge.sncl_patterns
        new_sncl_patterns = []
        UR=["temp0","temp1","temp2","temp3"]
        for sncl_pattern in concierge.sncl_patterns:
            UR[concierge.netOrder] = sncl_pattern.split('.')[concierge.netOrder]
            UR[concierge.staOrder] = sncl_pattern.split('.')[concierge.staOrder]
            UR[concierge.locOrder] = sncl_pattern.split('.')[concierge.locOrder]
            UR[concierge.chanOrder] = sncl_pattern.split('.')[concierge.chanOrder]
            if len(UR[concierge.chanOrder]) == 3:
                UR[concierge.chanOrder]=UR[concierge.chanOrder][:-1] + '?'
            new_sncl_pattern = ".".join(UR)
            new_sncl_patterns.append(new_sncl_pattern)
        concierge.sncl_patterns = new_sncl_patterns    
 
        try:        
            availability = concierge.get_availability("orientation", starttime=halfHourStart, endtime=halfHourEnd,
                                                      longitude=event.longitude, latitude=event.latitude,
                                                      minradius=eventMinradius, maxradius=eventMaxradius)
        except NoAvailableDataError as e:
            logger.info('Skipping event with no available data')
            concierge.sncl_patterns = original_sncl_patterns
            continue
        except Exception as e:
            logger.warning('Skipping event because concierge.get_availability failed: %s' % (e))
            concierge.sncl_patterns = original_sncl_patterns
            continue
        if availability is None:
            logger.info("Skipping event with no available data")
            concierge.sncl_patterns = original_sncl_patterns
            continue

        concierge.sncl_patterns = original_sncl_patterns
                    
        # Apply the channelFilter
        availability = availability[availability.channel.str.contains(channelFilter)]      

        #logger.debug(availability)

        # Sanity check that some SNCLs exist
        if availability.shape[0] == 0:
            logger.info('Skipping event because no stations are available')
            continue
    
        ############################################################
        # Loop through the SN.L combinations
        ############################################################
    
        # Channel types (as opposed to orientation) will contain only the first two characters
        channelType = availability.channel.apply(lambda x: x[0:2])

        # Find unique network-station-location combinations
        sn_lIds = availability.network + '.' + availability.station + '.' + availability.location + '.' + channelType
    
        # Add sn_lId to the availability dataframe for easy detection
        availability.insert(availability.shape[1],'sn_lId',sn_lIds)

        # ----- All available SNCLs -------------------------------------------------

        for idx, sn_lId in enumerate(sorted(list(set(sn_lIds)))):

            logger.info('%03d Calculating orientationCheck metrics for %s' % (idx, sn_lId))

            
            sn_lAvailability = availability[availability.sn_lId == sn_lId]
            
            if sn_lAvailability.shape[0] != 3:
                logger.info('Skipping %s because only %d channels were found at this SN.L (3 required)' % (sn_lId, sn_lAvailability.shape[0]))
                continue

            # If any of the channels don't have metadata, skip this sn.l
            if any(sn_lAvailability.samplerate.isnull().values):
                logger.info('Skipping %s because at least one channel is missing metadata' % sn_lId)
                continue

            # Determine N, E and Z channels
            N_or_1_mask = sn_lAvailability.channel.str.contains('..N') | sn_lAvailability.channel.str.contains('..1')
            E_or_2_mask = sn_lAvailability.channel.str.contains('..E') | sn_lAvailability.channel.str.contains('..2')
            Z_mask = sn_lAvailability.channel.str.contains('..Z')
            Channel_1 = sn_lAvailability[N_or_1_mask].iloc[0]
            Channel_2 = sn_lAvailability[E_or_2_mask].iloc[0]
            ZChannel = sn_lAvailability[Z_mask].iloc[0]
    
            # Calculate various distances and surface travel time
            numpy2ri.activate()
#             pandas2ri.activate()
            distaz = irisseismic.getDistaz(event.latitude,event.longitude,ZChannel.latitude,ZChannel.longitude)
            surfaceDistance = irisseismic.surfaceDistance(event.latitude,event.longitude,ZChannel.latitude,ZChannel.longitude)[0]
            surfaceTravelTime = surfaceDistance / 4.0 # km  / (km/sec)
#             pandas2ri.deactivate()
            numpy2ri.deactivate()
            

            # Get the data -----------------------------------------
        
            #         request 3-channel instrument-corrected (or scaled) data for one station/loc/sample_rate
            #             starting 20s before the predicted Rayleigh wave and ending 600s after.
            #         Apply a 10% cosine taper to each channel
            #         Bandpass filter from 0.02 to 0.04 Hz (50-25s)
            #         Take the Hilbert transform of the Z channel
        
            windowStart = event.time + surfaceTravelTime - windowSecsBefore
            windowEnd = event.time + surfaceTravelTime + windowSecsAfter

            logger.debug("Looking for data for %s, %s, %s from %s to %s" % (Channel_1.snclId, Channel_2.snclId, ZChannel.snclId, windowStart.strftime("%Y-%m-%dT%H:%M:%S"), windowEnd.strftime("%Y-%m-%dT%H:%M:%S")))

            try:
                stN = concierge.get_dataselect(Channel_1.network, Channel_1.station, Channel_1.location, Channel_1.channel,
                                               windowStart, windowEnd, inclusiveEnd=False)
            except Exception as e:
                if str(e).lower().find('no data') > -1:
                    logger.info('No data available for %s' % (Channel_1.snclId[:-1]))
                elif str(e).lower().find('multiple epochs') > -1:
                    logger.info('Skipping %s because multiple metadata epochs found' % (av.snclId))
                else:
                    logger.warning('No data available for %s from %s: %s' % (Channel_1.snclId, concierge.dataselect_url, e))
                continue
        
            try:
                stE = concierge.get_dataselect(Channel_2.network, Channel_2.station, Channel_2.location, Channel_2.channel,
                                               windowStart, windowEnd, inclusiveEnd=False)
            except Exception as e:
                if str(e).lower().find('no data') > -1:
                    logger.info('No data available for %s' % (Channel_2.snclId[:-1]))
                elif str(e).lower().find('multiple epochs') > -1:
                    logger.info('Skipping %s because multiple metadata epochs found' % (av.snclId))
                else:
                    logger.info('No data available for %s from %s: %s' % (Channel_2.snclId, concierge.dataselect_url, e))
                continue
        
            try:
                stZ = concierge.get_dataselect(ZChannel.network, ZChannel.station, ZChannel.location, ZChannel.channel,
                                               windowStart, windowEnd, inclusiveEnd=False)
            except Exception as e:
                if str(e).lower().find('no data') > -1:
                    logger.info('No data available for %s' % (ZChannel.snclId[:-1]))
                elif str(e).lower().find('multiple epochs') > -1:
                    logger.info('Skipping %s because multiple metadata epochs found' % (av.snclId))
                else:
                    logger.info('No data available for %s from %s: %s' % (ZChannel.snclId, concierge.dataselect_url, e))
                continue
        
        
            # If metadata indicates reversed polarity (dip>0), invert the amplitudes 
            if (ZChannel.dip > 0):
                stZ = irisseismic.multiplyBy(stZ,-1)
        
            if len(utils.get_slot(stN,'traces')) > 1 or len(utils.get_slot(stE,'traces')) > 1 or len(utils.get_slot(stZ,'traces')) > 1:
                logger.info('Skipping %s because it has gaps' % (sn_lId)) 
                continue
        
            # complain if sample lengths differ by more than 1 sample
            l1 = utils.get_slot(stN,'npts')
            l2 = utils.get_slot(stE,'npts')
            l3 = utils.get_slot(stZ,'npts')
      
            if( abs(l1 - l2) > 1  or abs(l1 - l3) > 1 ):
                logger.info('Skipping %s because the number of data samples differs between channels. Incompatible lengths stN=%d, stE=%d, stZ=%d' % (sn_lId,l1,l2,l3))
                continue
            else:
                max_length = min(l1, l2, l3)
                
                
            # NOTE:  This next function captures a chunk of functionality that involves direct
            # NOTE:  manipulation of individual slots in Stream objects.
            # NOTE:  This requires some R knowledge and rpy2 trickery that doesn't belong in 
            # NOTE:  the business logic python code.
 
            (stN, stE, stZ, HZ) = irisseismic.trim_taper_filter(stN, stE, stZ, max_length, taper, filterArgs)
            
            
            #         For trial empirical BHN/BH1 channel azimuths X = 0 to 360 in degrees (X is bearing from N):
            #             Rotate the two horizontal channels to find the radial component R
            #                 (R is the vector sum of the 2 horizontal channels in the back azimuth direction)
            #                 Assume BHE/BH2 is 90 degrees clockwise from BHN/BH1.
            #             Calculate the cross-correlation of R and H{Z} at zero lag:
            #                 Szr = sum(i): [R[t(i)] * H{Z[t(i)]}] where i = 1,...,N samples
            #             Calculate the auto-correlations of R and H{Z} at zero lag:
            #                 Szz = sum(i): [H{Z[t(i)]}^2] where i = 1,...,N samples
            #                 Srr = sum(i): [R[t(i)]^2] where i = 1,...,N samples
            #             Calculate and save 2 separate normalized correlation coefficients:
            #                 a) Czr = Szr / sqrt(Szz*Srr)
            #                 b) C*zr = Szr / Srr

            # Prefill Szz as it doesn't depend on the angle
            HZ_data = pd.Series(utils.get_slot(HZ,'data'))
            SzzValue = sum(HZ_data * HZ_data)
            Szz = pd.Series([SzzValue] * 360)
            Szr = pd.Series([np.NaN] * 360)
            Srr = pd.Series([np.NaN] * 360)

            # Calculate correlations as a function of angle
            rotateOK = True
            for angle in range(1,360,degreeIncrement):
                
                #if angle % 10 == 0:
                #    logger.debug('rotate2D angle = %d' % angle)
                    
                try:
                    stR = irisseismic.rotate2D(stN, stE, angle)[0]
                except Exception as e:
                    logger.warning('skipping %s: irisseismic.rotate2D failed:  %s' % (sn_lId, e.message))
                    rotateOK = False
                    break
                R_data = pd.Series(utils.get_slot(stR,'data'))
                Srr[angle] = sum(R_data * R_data)
                Szr[angle] = sum(HZ_data * R_data)
              
            # an error in the loop means we skip this SNL, go to next in loop
            if not rotateOK:
                continue
                
            # Normalized correlation coefficients
            Czr = Szr / (Szz*Srr).pow(.5)
            C_zr = Szr / Szz
            

            maxCzr = Czr.max(skipna=True)
            maxC_zr = C_zr.max(skipna=True)

            angleAtMaxCzr = int( list(Czr[Czr == maxCzr].index)[0] )
            angleAtMaxC_zr = int( list(C_zr[C_zr == maxC_zr].index)[0] )

            azimuth_R = angleAtMaxC_zr % 360
            azimuth_T = (azimuth_R + 90) % 360

            #         Find the orientation X with the maximum C*zr and:
            #             report empirical X, X+90, 
            #             report metadata azimuths for horizontal channels
            #             report Czr & C*zr 
            #             report start and end of data window
            #
            #
            # REC Feb 2014 -- change the attribute names based on Mary Templeton's recommendations
            #              -- also add an event magnitude attribute
            # azimuth_R
            # backAzimuth
            # azimuth_Y_obs        (= backAzimuth - azimuth_R)
            # azimuth_X_obs        (= azimuth_Y_obs + 90)
            # azimuth_Y_meta       (azimuth_N renamed)
            # azimuth_X_meta       (azimuth_E renamed)
            # max_Czr
            # max_C_zr
            # magnitude

            azimuth_Y_obs = (float(distaz.backAzimuth) - azimuth_R) % 360
            azimuth_X_obs = (azimuth_Y_obs + 90.0) % 360

            elementNames = ["azimuth_R","backAzimuth","azimuth_Y_obs","azimuth_X_obs","azimuth_Y_meta","azimuth_X_meta","max_Czr","max_C_zr","magnitude"]
            elementValues = [azimuth_R, float(distaz.backAzimuth), azimuth_Y_obs, azimuth_X_obs,
                               float(Channel_1.azimuth), float(Channel_2.azimuth), maxCzr, maxC_zr, float(event.magnitude)]

            # Create metric
            df = irisseismic.generalValueMetric(utils.get_slot(stZ, 'id'), windowStart, windowEnd,
                                               'orientation_check', elementNames, elementValues)
            dataframes.append(df)
                        
        # END of sn_lId loop

    # END of event loop

    # Concatenate dataframes before returning ----------------------------------
    
    if len(dataframes) == 0:
        logger.warning('"orientation_check" metric calculation generated zero metrics')
        return None
    else:
        result = pd.concat(dataframes, ignore_index=True)    
        result.reset_index(drop=True, inplace=True)
        return(result)


# ------------------------------------------------------------------------------


if __name__ == '__main__':
    import doctest
    doctest.testmod(exclude_empty=True)
