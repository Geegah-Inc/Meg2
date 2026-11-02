# -*- coding: utf-8 -*-
"""
Created on Tue Apr 13 20:59:26 2021

@author: Justin
"""
#import master_function as mf
import matplotlib.patches as mpatches
import time
#%%
def genNFramesImagesSMALLER_DATA_MAG_PHASE(num_frames_to_image,start_frame,stop_frame,img_save_dir,AIR_MAG,AIR_PHASE,rawdata_save_dir_echo,rawdata_save_dir_noecho, FIG_SCALES_MAG,FIG_SCALES_PHASE):
    import matplotlib.pyplot as plt
    import numpy as np

    #set up plot
    
    #plot base voltage
    fig5,ax5 = plt.subplots(1,2,figsize=[14, 8])
    
    mytitle = fig5.suptitle('Magnitude and Phase')
    ##mytitle.set_text('TEST TEST')
    #pos500 = ax5[0,0].imshow(np.rot90(BL_I_VOLTS,2),cmap="inferno",vmin=FIG_SCALES_BASE[0], vmax=FIG_SCALES_BASE[1])
    #pos510 = ax5[1,0].imshow(np.rot90(BL_Q_VOLTS,2),cmap="inferno",vmin=FIG_SCALES_BASE[2], vmax=FIG_SCALES_BASE[3])
    
    #pos501 = ax5[0,1].imshow(np.rot90(BL_I_VOLTS,2),cmap="inferno",vmin=FIG_SCALES_MEAS[0], vmax=FIG_SCALES_MEAS[1])
    #pos511 = ax5[1,1].imshow(np.rot90(BL_Q_VOLTS,2),cmap="inferno",vmin=FIG_SCALES_MEAS[2], vmax=FIG_SCALES_MEAS[3])
    
    
    #plot difference in millivolts
    pos502 = ax5[0].imshow(np.rot90(AIR_MAG/AIR_MAG),cmap="inferno",vmin=FIG_SCALES_MAG[0], vmax=FIG_SCALES_MAG[1])
    pos512 = ax5[1].imshow(np.rot90(AIR_PHASE,2),cmap="inferno",vmin=FIG_SCALES_PHASE[0], vmax=FIG_SCALES_PHASE[1])
    
    #set colorbars for all subplots
    # cbar_5_00 = fig5.colorbar(pos500, ax=ax5[0,0])
    # ax5[0,0].set_title('I Data Base')
    # cbar_5_00.ax.set_ylabel('Voltage (V)', rotation=90)
    
    # cbar_5_10 = fig5.colorbar(pos510, ax=ax5[1,0])
    # ax5[1,0].set_title('Q Data Base')
    # cbar_5_10.ax.set_ylabel('Voltage (V)', rotation=90)
    
    # cbar_5_01 = fig5.colorbar(pos501, ax=ax5[0,1])
    # ax5[0,1].set_title('I Data Meas')
    # cbar_5_01.ax.set_ylabel('Voltage (V)', rotation=90)
    
    # cbar_5_11 = fig5.colorbar(pos511, ax=ax5[1,1])
    # ax5[1,1].set_title('Q Data Meas')
    # cbar_5_11.ax.set_ylabel('Voltage (V)', rotation=90)
    
    cbar_5_02=fig5.colorbar(pos502, ax=ax5[0])
    ax5[0].set_title('Normalized Magnitude')
    cbar_5_02.ax.set_ylabel('Measured Mag/Air Mag (0 to 1)', rotation=90)
    
    cbar_5_12 = fig5.colorbar(pos512, ax=ax5[1])
    ax5[1].set_title('Phase')
    cbar_5_12.ax.set_ylabel('Radians', rotation=90)
    
    base_title = 'I and Q Images in Magnitude/Phase, Frame: '
    numframedigits = len(str(num_frames_to_image))
    for mycount2 in range(start_frame,stop_frame):
        meas_filename = rawdata_save_dir_echo+"DATA"+str(mycount2).zfill(numframedigits)+".dat"
        meas_noecho_filename = rawdata_save_dir_noecho+"DATA"+str(mycount2).zfill(numframedigits)+".dat"
        
        ME_I_ADC, ME_Q_ADC, ME_I_VOLTS, ME_Q_VOLTS = loadSavedRawData(meas_filename)
        MNE_I_ADC, MNE_Q_ADC, MNE_I_VOLTS, MNE_Q_VOLTS = loadSavedRawData(meas_noecho_filename)
        
        ME_I_ACTUAL = ME_Q_VOLTS
        ME_Q_ACTUAL = ME_I_VOLTS
        MNE_I_ACTUAL = MNE_Q_VOLTS
        MNE_Q_ACTUAL = MNE_I_VOLTS
        
        MEAS_MAG = np.sqrt(np.square(ME_I_ACTUAL-MNE_I_ACTUAL)+np.square(ME_Q_ACTUAL-MNE_Q_ACTUAL))
        MEAS_PHASE = np.arctan2((ME_I_ACTUAL-MNE_I_ACTUAL),(ME_Q_ACTUAL-MNE_Q_ACTUAL))

        
        #plot figure
        #update title to reflect frame count
        mytitle.set_text(base_title+str(mycount2).zfill(numframedigits) +' of ' +str(num_frames_to_image-1))
        
        ##update measured voltage (in volts)
        #pos501.set_data(np.rot90((I_VOLTS_RTS),2))
        #pos511.set_data(np.rot90((Q_VOLTS_RTS),2))
        #update subtracted voltage (in millivolts)
        pos502.set_data(np.rot90(MEAS_MAG/AIR_MAG,2))
        pos512.set_data(np.rot90(MEAS_PHASE,2))
        #redraw
        fig5.canvas.draw_idle()
        plt.pause(0.001)
        
        #save figure
        framefig_file_name = img_save_dir + "frame"+str(mycount2).zfill(numframedigits)+".png"
        plt.savefig(framefig_file_name)




def genNFramesImagesSMALLER_DATA(num_frames_to_image,start_frame,stop_frame,img_save_dir,savedbaselinebinfilename,rawdata_save_dir, FIG_SCALES_SUB):
    import matplotlib.pyplot as plt
    import numpy as np
    BL_I_ADC, BL_Q_ADC, BL_I_VOLTS, BL_Q_VOLTS = loadSavedRawData(savedbaselinebinfilename)
    #set up plot
    
    #plot base voltage
    fig5,ax5 = plt.subplots(1,2,figsize=[14, 8])
    
    mytitle = fig5.suptitle('I and Q Images in Voltage: Base, Measured, and Subtracted')
    ##mytitle.set_text('TEST TEST')
    #pos500 = ax5[0,0].imshow(np.rot90(BL_I_VOLTS,2),cmap="inferno",vmin=FIG_SCALES_BASE[0], vmax=FIG_SCALES_BASE[1])
    #pos510 = ax5[1,0].imshow(np.rot90(BL_Q_VOLTS,2),cmap="inferno",vmin=FIG_SCALES_BASE[2], vmax=FIG_SCALES_BASE[3])
    
    #pos501 = ax5[0,1].imshow(np.rot90(BL_I_VOLTS,2),cmap="inferno",vmin=FIG_SCALES_MEAS[0], vmax=FIG_SCALES_MEAS[1])
    #pos511 = ax5[1,1].imshow(np.rot90(BL_Q_VOLTS,2),cmap="inferno",vmin=FIG_SCALES_MEAS[2], vmax=FIG_SCALES_MEAS[3])
    
    
    #plot difference in millivolts
    pos502 = ax5[0].imshow(np.rot90(1000*(BL_I_VOLTS-BL_I_VOLTS),2),cmap="inferno",vmin=FIG_SCALES_SUB[0], vmax=FIG_SCALES_SUB[1])
    pos512 = ax5[1].imshow(np.rot90(1000*(BL_Q_VOLTS-BL_Q_VOLTS),2),cmap="inferno",vmin=FIG_SCALES_SUB[2], vmax=FIG_SCALES_SUB[3])
    
    #set colorbars for all subplots
    # cbar_5_00 = fig5.colorbar(pos500, ax=ax5[0,0])
    # ax5[0,0].set_title('I Data Base')
    # cbar_5_00.ax.set_ylabel('Voltage (V)', rotation=90)
    
    # cbar_5_10 = fig5.colorbar(pos510, ax=ax5[1,0])
    # ax5[1,0].set_title('Q Data Base')
    # cbar_5_10.ax.set_ylabel('Voltage (V)', rotation=90)
    
    # cbar_5_01 = fig5.colorbar(pos501, ax=ax5[0,1])
    # ax5[0,1].set_title('I Data Meas')
    # cbar_5_01.ax.set_ylabel('Voltage (V)', rotation=90)
    
    # cbar_5_11 = fig5.colorbar(pos511, ax=ax5[1,1])
    # ax5[1,1].set_title('Q Data Meas')
    # cbar_5_11.ax.set_ylabel('Voltage (V)', rotation=90)
    
    cbar_5_02=fig5.colorbar(pos502, ax=ax5[0])
    ax5[0].set_title('I Data Meas - Base')
    cbar_5_02.ax.set_ylabel('Voltage (mV)', rotation=90)
    
    cbar_5_12 = fig5.colorbar(pos512, ax=ax5[1])
    ax5[1].set_title('Q Data Meas - Base')
    cbar_5_12.ax.set_ylabel('Voltage (mV)', rotation=90)
    
    base_title = 'I and Q Images in Voltage: Base, Measured, and Subtracted, Frame: '
    numframedigits = len(str(num_frames_to_image))
    for mycount2 in range(start_frame,stop_frame):
        binfilename = rawdata_save_dir+"DATA"+str(mycount2).zfill(numframedigits)+".dat"
        f = open(binfilename, 'rb')
        bindat = f.read()
        f.close()
        #convert binary data to matrix
        J_MYIMAGE_I4, J_MYIMAGE_Q4 = convertToIQImage(bindat);
        #convert matrix to volts and actual ADC value
        I_ADC_RTS, Q_ADC_RTS, I_VOLTS_RTS, Q_VOLTS_RTS = convertADCToVolts(J_MYIMAGE_I4, J_MYIMAGE_Q4)
        
        #plot figure
        #update title to reflect frame count
        mytitle.set_text(base_title+str(mycount2).zfill(numframedigits) +' of ' +str(num_frames_to_image-1))
        
        ##update measured voltage (in volts)
        #pos501.set_data(np.rot90((I_VOLTS_RTS),2))
        #pos511.set_data(np.rot90((Q_VOLTS_RTS),2))
        #update subtracted voltage (in millivolts)
        pos502.set_data(np.rot90(1000*(I_VOLTS_RTS-BL_I_VOLTS),2))
        pos512.set_data(np.rot90(1000*(Q_VOLTS_RTS-BL_Q_VOLTS),2))
        #redraw
        fig5.canvas.draw_idle()
        plt.pause(0.001)
        
        #save figure
        framefig_file_name = img_save_dir + "frame"+str(mycount2).zfill(numframedigits)+".png"
        plt.savefig(framefig_file_name)

#generate N frames into video from saved images
def genFrameVidFromImg(num_frames_to_image,start_frame,stop_frame,fps,img_save_dir,vid_save_dir):
    #import cv2
    img_array = []
    
    numframedigits = len(str(num_frames_to_image))
    for count3 in range(start_frame,stop_frame):
        imgname = img_save_dir + "frame"+str(count3)+".png"
        
        img = cv2.imread(imgname)
        height, width, layers = img.shape
        size = (width,height)
        img_array.append(img)
    
    
    vid_file_name = vid_save_dir + 'video.avi'
    out = cv2.VideoWriter(vid_file_name,cv2.VideoWriter_fourcc(*'DIVX'), fps, size)
     
    for i in range(len(img_array)):
        out.write(img_array[i])
    out.release()




#generate N frames CSV Files

def genNFramesCSVS(num_frames_to_image,start_frame,stop_frame,csv_save_dir,savedbaselinebinfilename,rawdata_save_dir):
    import numpy as np
    BL_I_ADC, BL_Q_ADC, BL_I_VOLTS, BL_Q_VOLTS = loadSavedRawData(savedbaselinebinfilename)
    #set up plot
    
    numframedigits = len(str(num_frames_to_image))
    for mycount2 in range(start_frame,stop_frame):
        binfilename = rawdata_save_dir+"frame"+str(mycount2).zfill(numframedigits)+".dat"
        f = open(binfilename, 'rb')
        bindat = f.read()
        f.close()
        #convert binary data to matrix
        J_MYIMAGE_I4, J_MYIMAGE_Q4 = convertToIQImage(bindat);
        #convert matrix to volts and actual ADC value
        I_ADC_RTS, Q_ADC_RTS, I_VOLTS_RTS, Q_VOLTS_RTS = convertADCToVolts(J_MYIMAGE_I4, J_MYIMAGE_Q4)
        
        
        #save csv file
        #csv_save_dir
        np.savetxt(csv_save_dir+"I_ADC"+str(mycount2).zfill(numframedigits)+".csv",I_ADC_RTS,delimiter = ",")
        np.savetxt(csv_save_dir+"I_VOLTS"+str(mycount2).zfill(numframedigits)+".csv",I_VOLTS_RTS,delimiter = ",")
        np.savetxt(csv_save_dir+"Q_ADC"+str(mycount2).zfill(numframedigits)+".csv",Q_ADC_RTS,delimiter = ",")
        np.savetxt(csv_save_dir+"Q_VOLTS"+str(mycount2).zfill(numframedigits)+".csv",Q_VOLTS_RTS,delimiter = ",")
        
        np.savetxt(csv_save_dir+"I_ADC_SUB"+str(mycount2).zfill(numframedigits)+".csv",I_ADC_RTS-BL_I_ADC,delimiter = ",")
        np.savetxt(csv_save_dir+"I_VOLTS_SUB"+str(mycount2).zfill(numframedigits)+".csv",I_VOLTS_RTS-BL_I_VOLTS,delimiter = ",")
        np.savetxt(csv_save_dir+"Q_ADC_SUB"+str(mycount2).zfill(numframedigits)+".csv",Q_ADC_RTS-BL_Q_ADC,delimiter = ",")
        np.savetxt(csv_save_dir+"Q_VOLTS_SUB"+str(mycount2).zfill(numframedigits)+".csv",Q_VOLTS_RTS-BL_Q_VOLTS,delimiter = ",")
        print("Currently at frame ", mycount2)

#generate N frames png files
#num_frames_to_image = number of frames imaged
#savedbaselinebinfilename: saved baseline .dat file
#rawdata_save_dir: folder where the saved frame .dat data is located
#Figure Scale Setting: FIG_SCALES_BASE,FIG_SCALES_MEAS,FIG_SCALES_SUB
#[VOLTS_MIN_I,VOLTS_MAX_I,VOLTS_MIN_Q,VOLTS_MAX_Q ]
#good image settings:
#FIG_SCALES_BASE = [2, 4, 2, 4]
#FIG_SCALES_MEAS = [2, 4, 2, 4]
#FIG_SCALES_SUB = [-100, 100, -100, 100] this is in millivolts
def genNFramesImages(num_frames_to_image,start_frame,stop_frame,img_save_dir,savedbaselinebinfilename,rawdata_save_dir,FIG_SCALES_BASE,FIG_SCALES_MEAS,FIG_SCALES_SUB):
    import matplotlib.pyplot as plt
    import numpy as np
    BL_I_ADC, BL_Q_ADC, BL_I_VOLTS, BL_Q_VOLTS = loadSavedRawData(savedbaselinebinfilename)
    #set up plot
    
    #plot base voltage
    fig5,ax5 = plt.subplots(2,3,figsize=[14, 8])
    
    mytitle = fig5.suptitle('I and Q Images in Voltage: Base, Measured, and Subtracted')
    #mytitle.set_text('TEST TEST')
    pos500 = ax5[0,0].imshow(np.rot90(BL_I_VOLTS,2),cmap="inferno",vmin=FIG_SCALES_BASE[0], vmax=FIG_SCALES_BASE[1])
    pos510 = ax5[1,0].imshow(np.rot90(BL_Q_VOLTS,2),cmap="inferno",vmin=FIG_SCALES_BASE[2], vmax=FIG_SCALES_BASE[3])
    
    pos501 = ax5[0,1].imshow(np.rot90(BL_I_VOLTS,2),cmap="inferno",vmin=FIG_SCALES_MEAS[0], vmax=FIG_SCALES_MEAS[1])
    pos511 = ax5[1,1].imshow(np.rot90(BL_Q_VOLTS,2),cmap="inferno",vmin=FIG_SCALES_MEAS[2], vmax=FIG_SCALES_MEAS[3])
    
    
    #plot difference in millivolts
    pos502 = ax5[0,2].imshow(np.rot90(1000*(BL_I_VOLTS-BL_I_VOLTS),2),cmap="inferno",vmin=FIG_SCALES_SUB[0], vmax=FIG_SCALES_SUB[1])
    pos512 = ax5[1,2].imshow(np.rot90(1000*(BL_Q_VOLTS-BL_Q_VOLTS),2),cmap="inferno",vmin=FIG_SCALES_SUB[2], vmax=FIG_SCALES_SUB[3])
    
    #set colorbars for all subplots
    cbar_5_00 = fig5.colorbar(pos500, ax=ax5[0,0])
    ax5[0,0].set_title('I Data Base')
    cbar_5_00.ax.set_ylabel('Voltage (V)', rotation=90)
    
    cbar_5_10 = fig5.colorbar(pos510, ax=ax5[1,0])
    ax5[1,0].set_title('Q Data Base')
    cbar_5_10.ax.set_ylabel('Voltage (V)', rotation=90)
    
    cbar_5_01 = fig5.colorbar(pos501, ax=ax5[0,1])
    ax5[0,1].set_title('I Data Meas')
    cbar_5_01.ax.set_ylabel('Voltage (V)', rotation=90)
    
    cbar_5_11 = fig5.colorbar(pos511, ax=ax5[1,1])
    ax5[1,1].set_title('Q Data Meas')
    cbar_5_11.ax.set_ylabel('Voltage (V)', rotation=90)
    
    cbar_5_02=fig5.colorbar(pos502, ax=ax5[0,2])
    ax5[0,2].set_title('I Data Meas - Base')
    cbar_5_02.ax.set_ylabel('Voltage (mV)', rotation=90)
    
    cbar_5_12 = fig5.colorbar(pos512, ax=ax5[1,2])
    ax5[1,2].set_title('Q Data Meas - Base')
    cbar_5_12.ax.set_ylabel('Voltage (mV)', rotation=90)
    
    base_title = 'I and Q Images in Voltage: Base, Measured, and Subtracted, Frame: '
    numframedigits = len(str(num_frames_to_image))
    for mycount2 in range(start_frame,stop_frame):
        binfilename = rawdata_save_dir+"frame"+str(mycount2).zfill(numframedigits)+".dat"
        f = open(binfilename, 'rb')
        bindat = f.read()
        f.close()
        #convert binary data to matrix
        J_MYIMAGE_I4, J_MYIMAGE_Q4 = convertToIQImage(bindat);
        #convert matrix to volts and actual ADC value
        I_ADC_RTS, Q_ADC_RTS, I_VOLTS_RTS, Q_VOLTS_RTS = convertADCToVolts(J_MYIMAGE_I4, J_MYIMAGE_Q4)
        
        #plot figure
        #update title to reflect frame count
        mytitle.set_text(base_title+str(mycount2).zfill(numframedigits) +' of ' +str(num_frames_to_image-1))
        
        #update measured voltage (in volts)
        pos501.set_data(np.rot90((I_VOLTS_RTS),2))
        pos511.set_data(np.rot90((Q_VOLTS_RTS),2))
        #update subtracted voltage (in millivolts)
        pos502.set_data(np.rot90(1000*(I_VOLTS_RTS-BL_I_VOLTS),2))
        pos512.set_data(np.rot90(1000*(Q_VOLTS_RTS-BL_Q_VOLTS),2))
        #redraw
        fig5.canvas.draw_idle()
        plt.pause(0.001)
        
        #save figure
        framefig_file_name = img_save_dir + "frame"+str(mycount2).zfill(numframedigits)+".png"
        plt.savefig(framefig_file_name)
        
def genNFramesImagesSMALLER(num_frames_to_image,start_frame,stop_frame,img_save_dir,savedbaselinebinfilename,rawdata_save_dir, FIG_SCALES_SUB):
    import matplotlib.pyplot as plt
    import numpy as np
    BL_I_ADC, BL_Q_ADC, BL_I_VOLTS, BL_Q_VOLTS = loadSavedRawData(savedbaselinebinfilename)
    #set up plot
    
    #plot base voltage
    fig5,ax5 = plt.subplots(1,2,figsize=[14, 8])
    
    mytitle = fig5.suptitle('I and Q Images in Voltage: Base, Measured, and Subtracted')
    ##mytitle.set_text('TEST TEST')
    #pos500 = ax5[0,0].imshow(np.rot90(BL_I_VOLTS,2),cmap="inferno",vmin=FIG_SCALES_BASE[0], vmax=FIG_SCALES_BASE[1])
    #pos510 = ax5[1,0].imshow(np.rot90(BL_Q_VOLTS,2),cmap="inferno",vmin=FIG_SCALES_BASE[2], vmax=FIG_SCALES_BASE[3])
    
    #pos501 = ax5[0,1].imshow(np.rot90(BL_I_VOLTS,2),cmap="inferno",vmin=FIG_SCALES_MEAS[0], vmax=FIG_SCALES_MEAS[1])
    #pos511 = ax5[1,1].imshow(np.rot90(BL_Q_VOLTS,2),cmap="inferno",vmin=FIG_SCALES_MEAS[2], vmax=FIG_SCALES_MEAS[3])
    
    
    #plot difference in millivolts
    pos502 = ax5[0].imshow(np.rot90(1000*(BL_I_VOLTS-BL_I_VOLTS),2),cmap="inferno",vmin=FIG_SCALES_SUB[0], vmax=FIG_SCALES_SUB[1])
    pos512 = ax5[1].imshow(np.rot90(1000*(BL_Q_VOLTS-BL_Q_VOLTS),2),cmap="inferno",vmin=FIG_SCALES_SUB[2], vmax=FIG_SCALES_SUB[3])
    
    #set colorbars for all subplots
    # cbar_5_00 = fig5.colorbar(pos500, ax=ax5[0,0])
    # ax5[0,0].set_title('I Data Base')
    # cbar_5_00.ax.set_ylabel('Voltage (V)', rotation=90)
    
    # cbar_5_10 = fig5.colorbar(pos510, ax=ax5[1,0])
    # ax5[1,0].set_title('Q Data Base')
    # cbar_5_10.ax.set_ylabel('Voltage (V)', rotation=90)
    
    # cbar_5_01 = fig5.colorbar(pos501, ax=ax5[0,1])
    # ax5[0,1].set_title('I Data Meas')
    # cbar_5_01.ax.set_ylabel('Voltage (V)', rotation=90)
    
    # cbar_5_11 = fig5.colorbar(pos511, ax=ax5[1,1])
    # ax5[1,1].set_title('Q Data Meas')
    # cbar_5_11.ax.set_ylabel('Voltage (V)', rotation=90)
    
    cbar_5_02=fig5.colorbar(pos502, ax=ax5[0])
    ax5[0].set_title('I Data Meas - Base')
    cbar_5_02.ax.set_ylabel('Voltage (mV)', rotation=90)
    
    cbar_5_12 = fig5.colorbar(pos512, ax=ax5[1])
    ax5[1].set_title('Q Data Meas - Base')
    cbar_5_12.ax.set_ylabel('Voltage (mV)', rotation=90)
    
    base_title = 'I and Q Images in Voltage: Base, Measured, and Subtracted, Frame: '
    numframedigits = len(str(num_frames_to_image))
    for mycount2 in range(start_frame,stop_frame):
        binfilename = rawdata_save_dir+"frame"+str(mycount2).zfill(numframedigits)+".dat"
        f = open(binfilename, 'rb')
        bindat = f.read()
        f.close()
        #convert binary data to matrix
        J_MYIMAGE_I4, J_MYIMAGE_Q4 = convertToIQImage(bindat);
        #convert matrix to volts and actual ADC value
        I_ADC_RTS, Q_ADC_RTS, I_VOLTS_RTS, Q_VOLTS_RTS = convertADCToVolts(J_MYIMAGE_I4, J_MYIMAGE_Q4)
        
        #plot figure
        #update title to reflect frame count
        mytitle.set_text(base_title+str(mycount2).zfill(numframedigits) +' of ' +str(num_frames_to_image-1))
        
        ##update measured voltage (in volts)
        #pos501.set_data(np.rot90((I_VOLTS_RTS),2))
        #pos511.set_data(np.rot90((Q_VOLTS_RTS),2))
        #update subtracted voltage (in millivolts)
        pos502.set_data(np.rot90(1000*(I_VOLTS_RTS-BL_I_VOLTS),2))
        pos512.set_data(np.rot90(1000*(Q_VOLTS_RTS-BL_Q_VOLTS),2))
        #redraw
        fig5.canvas.draw_idle()
        plt.pause(0.001)
        
        #save figure
        framefig_file_name = img_save_dir + "frame"+str(mycount2).zfill(numframedigits)+".png"
        plt.savefig(framefig_file_name)

#load data from saved raw data array
def loadSavedRawData(file_name):
    f = open(file_name, 'rb')
    MYDAT = f.read()
    f.close()
    I_RAW, Q_RAW = convertToIQImage(MYDAT)
    I_ADC, Q_ADC, I_VOLTS, Q_VOLTS = convertADCToVolts(I_RAW, Q_RAW)
    return I_ADC, Q_ADC, I_VOLTS, Q_VOLTS

#image for a numnber of frames
#image for a numnber of frames
def imageNFrames(xem,num_frames_to_image,baseADC_data,rawdata_save_dir,ADC_TO_USE, saving_dir):
    import matplotlib.pyplot as plt
    import numpy as np
    #figure out how many zeros to use to pad save file name
    numframedigits = len(str(num_frames_to_image))
    #use baseline data for initial dummy image
    J_MYIMAGE_I3, J_MYIMAGE_Q3 = convertToIQImage(baseADC_data);
    #use same baseline data
    J_MYIMAGE_IBASE3, J_MYIMAGE_QBASE3 = convertToIQImage(baseADC_data);
    #convert to actual ADC value and actual voltage
    I_BASE_ADC_RT, Q_BASE_ADC_RT, I_BASE_VOLTS_RT, Q_BASE_VOLTS_RT = convertADCToVolts(J_MYIMAGE_IBASE3, J_MYIMAGE_QBASE3)
    I_ADC_RT, Q_ADC_RT, I_VOLTS_RT, Q_VOLTS_RT = convertADCToVolts(J_MYIMAGE_I3, J_MYIMAGE_Q3)
    
    #set up plot
    #plot base voltage
    fig2,ax2 = plt.subplots(2,3,figsize=[14, 8])

    mytitle = fig2.suptitle('Real Time I and Q Images in Voltage: Base, Measured, and Subtracted')
    #mytitle.set_text('TEST TEST')
    pos200 = ax2[0,0].imshow(np.flipud(np.rot90(I_BASE_VOLTS_RT,1)),cmap="inferno")
    pos210 = ax2[1,0].imshow(np.flipud(np.rot90(Q_BASE_VOLTS_RT,1)),cmap="inferno")
    
    pos201 = ax2[0,1].imshow(np.flipud(np.rot90(I_VOLTS_RT,1)),cmap="inferno")
    pos211 = ax2[1,1].imshow(np.flipud(np.rot90(Q_VOLTS_RT,1)),cmap="inferno")
    
    #plot difference in millivolts
    #pos202 = ax2[0,2].imshow(np.rot90(1000*(I_VOLTS_RT),2),cmap="inferno",vmin=-100, vmax=100)
    #pos212 = ax2[1,2].imshow(np.rot90(1000*(Q_VOLTS_RT),2),cmap="inferno",vmin=-100, vmax=100)
    im1 = I_VOLTS_RT-I_BASE_VOLTS_RT
    im2 = Q_VOLTS_RT-Q_BASE_VOLTS_RT
    
    pos202 = ax2[0,2].imshow(np.flipud(np.rot90(I_VOLTS_RT-I_BASE_VOLTS_RT,1)),cmap="inferno", vmin = im1.min(), vmax = im1.max())
    pos212 = ax2[1,2].imshow(np.flipud(np.rot90(Q_VOLTS_RT-Q_BASE_VOLTS_RT,1)),cmap="inferno", vmin = im2.min(), vmax = im2.max())
    #set colorbars for all subplots
    cbar_2_00 = fig2.colorbar(pos200, ax=ax2[0,0])
    ax2[0,0].set_title('I Data Base')
    cbar_2_00.ax.set_ylabel('Voltage (V)', rotation=90)
    
    cbar_2_10 = fig2.colorbar(pos210, ax=ax2[1,0])
    ax2[1,0].set_title('Q Data Base')
    cbar_2_10.ax.set_ylabel('Voltage (V)', rotation=90)
    
    cbar_2_01 = fig2.colorbar(pos201, ax=ax2[0,1])
    ax2[0,1].set_title('I Data Meas')
    cbar_2_01.ax.set_ylabel('Voltage (V)', rotation=90)
    
    cbar_2_11 = fig2.colorbar(pos211, ax=ax2[1,1])
    ax2[1,1].set_title('Q Data Meas')
    cbar_2_11.ax.set_ylabel('Voltage (V)', rotation=90)
    
    cbar_2_02=fig2.colorbar(pos202, ax=ax2[0,2])
    ax2[0,2].set_title('I Data Meas - Base')
    cbar_2_02.ax.set_ylabel('Voltage (mV)', rotation=90)
    
    cbar_2_12 = fig2.colorbar(pos212, ax=ax2[1,2])
    ax2[1,2].set_title('Q Data Meas - Base')
    cbar_2_12.ax.set_ylabel('Voltage (mV)', rotation=90)
    
    
    
    base_title = 'I and Q Images in Voltage: Base, Measured, and Subtracted, Frame: '
    for mycount in range(num_frames_to_image):
    
        #myt1 = time.time()
        xem.Open()
        
        # Acquire a frame
        ## Select ADC 2 and make sure the fake ADC is not selected
        xem.SelectADC(ADC_TO_USE) #1 for ADC2, 0 for ADC1
        xem.SelectFakeADC(0)
        
        ## Disable pattern generator
        xem.EnablePgen(0)
        ## Reset the pipe FIFO
        xem.ResetFifo()
        ## Enable pipe transfers
        xem.EnablePipeTransfer(1)
        ## Start an acquisition
        xem.StartAcq()
        # Get one frame
        myframedata = bytearray(128*128*2*2)
        nbytes = xem.GetPipeData(myframedata)
        xem.Close()
        
        #write to file
        f = open(rawdata_save_dir+"frame"+str(mycount).zfill(numframedigits)+".dat", "wb")
        f.write(myframedata)
        f.close()
        #myt3 = time.time()
        #convert binary data to matrix
        J_MYIMAGE_I3, J_MYIMAGE_Q3 = convertToIQImage(myframedata);
        #convert matrix to volts and actual ADC value
        I_ADC_RT, Q_ADC_RT, I_VOLTS_RT, Q_VOLTS_RT = convertADCToVolts(J_MYIMAGE_I3, J_MYIMAGE_Q3)
        
        #update title to reflect frame count
        mytitle.set_text(base_title+str(mycount)+' of ' +str(num_frames_to_image-1))
        
        #update measured voltage (in volts)
        pos201.set_data(np.flipud(np.rot90((I_VOLTS_RT),1)))
        pos211.set_data(np.flipud(np.rot90((Q_VOLTS_RT),1)))
        #update subtracted voltage (in millivolts)
        im1 = I_VOLTS_RT-I_BASE_VOLTS_RT
        pos202.set_data(np.flipud(np.rot90(I_VOLTS_RT-I_BASE_VOLTS_RT,1)))
        pos212.set_data(np.flipud(np.rot90(Q_VOLTS_RT-Q_BASE_VOLTS_RT,1)))
        #pos202.set_data(np.rot90(1000*(I_VOLTS_RT),2))
        #os212.set_data(np.rot90(1000*(Q_VOLTS_RT),2))
      
        #redraw
        fig2.canvas.draw_idle()
        fig2.savefig(saving_dir+'/'+'plot'+str(mycount)+'.png')
        plt.pause(0.001)
        #myt2 = time.time()
#%%
def imageLive_fast(xem,num_frames_to_image,baseADC_data,rawdata_save_dir,ADC_TO_USE, saving_dir):
    import matplotlib.pyplot as plt
    import numpy as np
    #figure out how many zeros to use to pad save file name
    numframedigits = len(str(num_frames_to_image))
    #use baseline data for initial dummy image
    J_MYIMAGE_I3, J_MYIMAGE_Q3 = convertToIQImage(baseADC_data);
    #use same baseline data
    J_MYIMAGE_IBASE3, J_MYIMAGE_QBASE3 = convertToIQImage(baseADC_data);
    #convert to actual ADC value and actual voltage
    I_BASE_ADC_RT, Q_BASE_ADC_RT, I_BASE_VOLTS_RT, Q_BASE_VOLTS_RT = convertADCToVolts(J_MYIMAGE_IBASE3, J_MYIMAGE_QBASE3)
    I_ADC_RT, Q_ADC_RT, I_VOLTS_RT, Q_VOLTS_RT = convertADCToVolts(J_MYIMAGE_I3, J_MYIMAGE_Q3)
    
    #set up plot
    fig2,ax2 = plt.subplots(1)
    mytitle = fig2.suptitle('Real-time Ultrasonic Images:  ')
   
    im2 = np.flipud(np.rot90(Q_VOLTS_RT-Q_BASE_VOLTS_RT,1))
    
    pos201 = ax2.imshow(im2, vmin = -0.2, vmax = 0.2, cmap = 'inferno', interpolation = 'bilinear')
    fig2.colorbar(pos201)
    base_title ='Real-time Ultrasonic image (V):  '
    i_myt_F = time.time()
    
    for mycount in range(num_frames_to_image):
        #print("Frame:" + str(mycount))
        xem.Open()
    
        # Acquire a frame
        ## Select ADC 2 and make sure the fake ADC is not selected
        xem.SelectADC(ADC_TO_USE) #1 for ADC2, 0 for ADC1
        xem.SelectFakeADC(0)
        
        ## Disable pattern generator
        xem.EnablePgen(0)
        ## Reset the pipe FIFO
        xem.ResetFifo()
        ## Enable pipe transfers
        xem.EnablePipeTransfer(1)
        ## Start an acquisition
        xem.StartAcq()
        # Get one frame
        myframedata = bytearray(128*128*2*2)
        nbytes = xem.GetPipeData(myframedata)
        
        xem.Close()
        
        #write to file
        f = open(rawdata_save_dir+"frame"+str(mycount).zfill(numframedigits)+".dat", "wb")
        f.write(myframedata)
        f.close()
        
        
        
        #convert binary data to matrix
        J_MYIMAGE_I3, J_MYIMAGE_Q3 = convertToIQImage(myframedata);
        #convert matrix to volts and actual ADC value
        I_ADC_RT, Q_ADC_RT, I_VOLTS_RT, Q_VOLTS_RT = convertADCToVolts(J_MYIMAGE_I3, J_MYIMAGE_Q3)
        
        #update title to reflect frame count
        mytitle.set_text(base_title+str(mycount)+' of ' +str(num_frames_to_image-1))
        
        sub_image = np.flipud(np.rot90(Q_VOLTS_RT-Q_BASE_VOLTS_RT,1))

        pos201.set_data(sub_image)
        pos201.set_clim(-0.1, 0.1)
       
        plt.pause(0.001)

        #redraw
        fig2.canvas.draw_idle()
        fig2.savefig(saving_dir+'/'+'plot'+str(mycount)+'.png')
        
        
    print("Done acquiring image data over echo and no echo")
    myt_D = time.time()
    total_time = myt_D - i_myt_F
    print(total_time)
    print('fps = '+str(num_frames_to_image/total_time))
        #myt2 = time.time()
 #%%
def imageLive_fast_NE(xem,num_frames_to_image,baseADC_data,rawdata_save_dir,ADC_TO_USE, saving_dir):
    import matplotlib.pyplot as plt
    import numpy as np
    #figure out how many zeros to use to pad save file name
    numframedigits = len(str(num_frames_to_image))
    #use baseline data for initial dummy image
    J_MYIMAGE_I3, J_MYIMAGE_Q3 = convertToIQImage(baseADC_data);
    #use same baseline data
    J_MYIMAGE_IBASE3, J_MYIMAGE_QBASE3 = convertToIQImage(baseADC_data);
    #convert to actual ADC value and actual voltage
    I_BASE_ADC_RT, Q_BASE_ADC_RT, I_BASE_VOLTS_RT, Q_BASE_VOLTS_RT = convertADCToVolts(J_MYIMAGE_IBASE3, J_MYIMAGE_QBASE3)
    I_ADC_RT, Q_ADC_RT, I_VOLTS_RT, Q_VOLTS_RT = convertADCToVolts(J_MYIMAGE_I3, J_MYIMAGE_Q3)
    #settings for no echo

    #terminal count
    #if you make this longer, you also need to sample ADC (ADC_CAP_SETTINGS) later to see an effect
    #otherwise the timing ends as soon as the ADC is done
    term_count_NE = 83+90
    
    #tuples to store timing settings
    #(start logic state, I start, I end, Q start, Q end)
    TX_SWITCH_EN_SETTINGS_NE = (0, 19, 42, 19, 42) 
    PULSE_AND_SETTINGS_NE = (0, 20, 42, 20, 42) 
    RX_SWITCH_EN_SETTINGS_NE =( 0, 42, 82+90, 42, 82+90) 
    GLOB_EN_SETTINGS_NE = (1, 71+90, 1023, 71+90, 1023) 
    LO_CTRL_SETTINGS_NE = (1, 1023, 1023, 42, 1023)
    ADC_CAP_SETTINGS_NE = (0, 80+90, 81+90, 80+90, 81+90)   # ADC_CAPTURE #80 81
    #set up plot
    fig2,ax2 = plt.subplots(1)
    mytitle = fig2.suptitle('Real-time Ultrasonic Images:  ')
   
    im2 = np.flipud(np.rot90(Q_VOLTS_RT-Q_BASE_VOLTS_RT,1))
    
    pos201 = ax2.imshow(im2, vmin = -0.2, vmax = 0.2, cmap = 'inferno', interpolation = 'bilinear')
    fig2.colorbar(pos201)
    base_title ='Real-time Ultrasonic image (V):  '
    i_myt_F = time.time()
    
    for mycount in range(num_frames_to_image):
        #print("Frame:" + str(mycount))
        xem.Open()
    
        # Acquire a frame
        ## Select ADC 2 and make sure the fake ADC is not selected
        xem.SelectADC(ADC_TO_USE) #1 for ADC2, 0 for ADC1
        xem.SelectFakeADC(0)
        
        ## Disable pattern generator
        xem.EnablePgen(0)
        ## Reset the pipe FIFO
        xem.ResetFifo()
        ## Enable pipe transfers
        xem.EnablePipeTransfer(1)
        ## Start an acquisition
        xem.StartAcq()
        # Get one frame
        myframedata = bytearray(128*128*2*2)
        nbytes = xem.GetPipeData(myframedata)
        
        xem.Close()
        
        #write to file
        f = open(rawdata_save_dir+"frame"+str(mycount).zfill(numframedigits)+".dat", "wb")
        f.write(myframedata)
        f.close()
        
        
        
        #convert binary data to matrix
        J_MYIMAGE_I3, J_MYIMAGE_Q3 = convertToIQImage(myframedata);
        #convert matrix to volts and actual ADC value
        I_ADC_RT, Q_ADC_RT, I_VOLTS_RT, Q_VOLTS_RT = convertADCToVolts(J_MYIMAGE_I3, J_MYIMAGE_Q3)
        
        #update title to reflect frame count
        mytitle.set_text(base_title+str(mycount)+' of ' +str(num_frames_to_image-1))
        
        sub_image = np.flipud(np.rot90(Q_VOLTS_RT-Q_BASE_VOLTS_RT,1))

        pos201.set_data(sub_image)
        pos201.set_clim(-0.1, 0.1)
       
        plt.pause(0.001)

        #redraw
        fig2.canvas.draw_idle()
        fig2.savefig(saving_dir+'/'+'plot'+str(mycount)+'.png')
        
        
    print("Done acquiring image data over echo and no echo")
    myt_D = time.time()
    total_time = myt_D - i_myt_F
    print(total_time)
    print('fps = '+str(num_frames_to_image/total_time))
        #myt2 = time.time()
#%%
def imageLive_touch(xem,num_frames_to_image,baseADC_data,rawdata_save_dir,ADC_TO_USE, saving_dir):
    import matplotlib.pyplot as plt
    import numpy as np
    #figure out how many zeros to use to pad save file name
    numframedigits = len(str(num_frames_to_image))
    #use baseline data for initial dummy image
    J_MYIMAGE_I3, J_MYIMAGE_Q3 = convertToIQImage(baseADC_data);
    #use same baseline data
    J_MYIMAGE_IBASE3, J_MYIMAGE_QBASE3 = convertToIQImage(baseADC_data);
    #convert to actual ADC value and actual voltage
    I_BASE_ADC_RT, Q_BASE_ADC_RT, I_BASE_VOLTS_RT, Q_BASE_VOLTS_RT = convertADCToVolts(J_MYIMAGE_IBASE3, J_MYIMAGE_QBASE3)
    I_ADC_RT, Q_ADC_RT, I_VOLTS_RT, Q_VOLTS_RT = convertADCToVolts(J_MYIMAGE_I3, J_MYIMAGE_Q3)
    
    #set up plot
    fig2,ax2 = plt.subplots(1)
    mytitle = fig2.suptitle('Real-time Ultrasonic Images:  ')
    im2 = np.flipud(np.rot90(Q_VOLTS_RT-Q_BASE_VOLTS_RT,1))
    
    pos201 = ax2.imshow(im2)
    
    base_title ='Real-time Ultrasonic image touch detection:  '
 
    from skimage.measure import label, regionprops
  
    for mycount in range(num_frames_to_image):
        print("Frame:" + str(mycount))
        xem.Open()
        # Acquire a frame
        ## Select ADC 2 and make sure the fake ADC is not selected
        xem.SelectADC(ADC_TO_USE) #1 for ADC2, 0 for ADC1
        xem.SelectFakeADC(0)
        
        ## Disable pattern generator
        xem.EnablePgen(0)
        ## Reset the pipe FIFO
        xem.ResetFifo()
        ## Enable pipe transfers
        xem.EnablePipeTransfer(1)
        ## Start an acquisition
        xem.StartAcq()
        # Get one frame
        myframedata = bytearray(128*128*2*2)
        nbytes = xem.GetPipeData(myframedata)
        xem.Close()
        
        #write to file
        f = open(rawdata_save_dir+"frame"+str(mycount).zfill(numframedigits)+".dat", "wb")
        f.write(myframedata)
        f.close()
        #convert binary data to matrix
        J_MYIMAGE_I3, J_MYIMAGE_Q3 = convertToIQImage(myframedata);
        #convert matrix to volts and actual ADC value
        I_ADC_RT, Q_ADC_RT, I_VOLTS_RT, Q_VOLTS_RT = convertADCToVolts(J_MYIMAGE_I3, J_MYIMAGE_Q3)
        
        #update title to reflect frame count
        mytitle.set_text(base_title+str(mycount)+' of ' +str(num_frames_to_image-1))
        
        sub_image = np.flipud(np.rot90(Q_VOLTS_RT-Q_BASE_VOLTS_RT,1))
        img_to_plot, img_to_process = mf.touch_sense(sub_image, 0.01,0.03)
        #update measured voltage (in volts)
        ax2.patches = []
        pos201.set_data(img_to_plot)
        #update subtracted voltage (in millivolts)
        box_thres = 50
        #rec_box, local_area, local_center = mf.touch_region_detect(img_to_plot, box_thres)
        #rec_box, local_area, local_center = touch_region_detect(img_to_process, box_thres)
        local_area = []
        local_center = []
        
        for region in regionprops(img_to_process.astype(int)):
        # take regions with large enough areas
            if region.area >= box_thres:
            # draw rectangle around segmented area
                minr, minc, maxr, maxc = region.bbox
                rect = mpatches.Rectangle((minc, minr), maxc - minc, maxr - minr,
                                      fill=False, edgecolor='red', linewidth=2)
                area = (maxc - minc)*(maxr - minr)
                local_area.append(area)
                xc = minc+(maxc- minc)/2
                yc = minr+(maxr - minr)/2
                local_center.append((xc,yc))
                ax2.add_patch(rect)
    
        beep_thres = 10
        mf.beep_threshold(local_area, local_center, beep_thres)

        #plt.show()
        plt.pause(0.001)
        
        #redraw
        fig2.canvas.draw_idle()
        fig2.savefig(saving_dir+'/'+'plot'+str(mycount)+'.png')
        
        #myt2 = time.time()
        
#%%
def saveDataCSVS(savedirname,I_ADC, Q_ADC, I_VOLTS, Q_VOLTS,I_BASE_ADC, Q_BASE_ADC, I_BASE_VOLTS, Q_BASE_VOLTS):
    import numpy as np
    np.savetxt(savedirname+"IimageADC.csv",I_ADC,delimiter = ",")
    np.savetxt(savedirname+"IimageVOLTS.csv",I_VOLTS,delimiter = ",")
    np.savetxt(savedirname+"QimageADC.csv",Q_ADC,delimiter = ",")
    np.savetxt(savedirname+"QimageVOLTS.csv",Q_VOLTS,delimiter = ",")
    
    np.savetxt(savedirname+"IimageADC_BASE.csv",I_BASE_ADC,delimiter = ",")
    np.savetxt(savedirname+"IimageVOLTS_BASE.csv",I_BASE_VOLTS,delimiter = ",")
    np.savetxt(savedirname+"QimageADC_BASE.csv",Q_BASE_ADC,delimiter = ",")
    np.savetxt(savedirname+"QimageVOLTS_BASE.csv",Q_BASE_VOLTS,delimiter = ",")
    
    np.savetxt(savedirname+"IimageADC_SUB.csv",I_ADC-I_BASE_ADC,delimiter = ",")
    np.savetxt(savedirname+"IimageVOLTS_SUB.csv",I_VOLTS-I_BASE_VOLTS,delimiter = ",")
    np.savetxt(savedirname+"QimageADC_SUB.csv",Q_ADC-Q_BASE_ADC,delimiter = ",")
    np.savetxt(savedirname+"QimageVOLTS_SUB.csv",Q_VOLTS-Q_BASE_VOLTS,delimiter = ",")

#plot a single figure and save it
def plotAndSaveSingleFigVolts(I_BASE_VOLTS,Q_BASE_VOLTS,I_VOLTS,Q_VOLTS,measfig_file_name):
    import matplotlib.pyplot as plt
    import numpy as np
    fig3,ax3 = plt.subplots(2,3,figsize=[14, 8])
    fig3.suptitle('I and Q Images in Voltage: Base, Measured, and Subtracted')
    #plot baseline
    pos300 = ax3[0,0].imshow(np.rot90(I_BASE_VOLTS,2),cmap="inferno")
    pos310 = ax3[1,0].imshow(np.rot90(Q_BASE_VOLTS,2),cmap="inferno")
    #plot measured data
    pos301 = ax3[0,1].imshow(np.rot90(I_VOLTS,2),cmap="inferno")
    pos311 = ax3[1,1].imshow(np.rot90(Q_VOLTS,2),cmap="inferno")
    
    #plot difference in millivolts
    pos302 = ax3[0,2].imshow(np.rot90(1000*(I_VOLTS-I_BASE_VOLTS),2),cmap="inferno")
    pos312 = ax3[1,2].imshow(np.rot90(1000*(Q_VOLTS-Q_BASE_VOLTS),2),cmap="inferno")
    
    #set colorbars for all subplots
    cbar_3_00 = fig3.colorbar(pos300, ax=ax3[0,0])
    ax3[0,0].set_title('I Data Base')
    cbar_3_00.ax.set_ylabel('Voltage (V)', rotation=90)
    
    cbar_3_10 = fig3.colorbar(pos310, ax=ax3[1,0])
    ax3[1,0].set_title('Q Data Base')
    cbar_3_10.ax.set_ylabel('Voltage (V)', rotation=90)
    
    cbar_3_01 = fig3.colorbar(pos301, ax=ax3[0,1])
    ax3[0,1].set_title('I Data Meas')
    cbar_3_01.ax.set_ylabel('Voltage (V)', rotation=90)
    
    cbar_3_11 = fig3.colorbar(pos311, ax=ax3[1,1])
    ax3[1,1].set_title('Q Data Meas')
    cbar_3_11.ax.set_ylabel('Voltage (V)', rotation=90)
    
    cbar_3_02=fig3.colorbar(pos302, ax=ax3[0,2])
    ax3[0,2].set_title('I Data Meas - Base')
    cbar_3_02.ax.set_ylabel('Voltage (mV)', rotation=90)
    
    cbar_3_12 = fig3.colorbar(pos312, ax=ax3[1,2])
    ax3[1,2].set_title('Q Data Meas - Base')
    cbar_3_12.ax.set_ylabel('Voltage (mV)', rotation=90)
    
    #save figure
    #measfig_file_name = savedirname + "measured_fig.png"
    plt.savefig(measfig_file_name)

#convert from raw byte data to ADC and voltage matrices
def convertByteToADCVOLTS(byte_data):
    J_MYIMAGE_I2, J_MYIMAGE_Q2 = convertToIQImage(byte_data)
    I_ADC, Q_ADC, I_VOLTS, Q_VOLTS = convertADCToVolts(J_MYIMAGE_I2, J_MYIMAGE_Q2)
    return I_ADC, Q_ADC, I_VOLTS, Q_VOLTS


#acquire single frame
#ADCNUM is 0 or 1
#file_name is the file name for the saved dat file
def acqSingleFrame(xem, ADCNUM, file_name):
    xem.Open()
    # Acquire a frame
    ## Select ADC 2 and make sure the fake ADC is not selected
    xem.SelectADC(ADCNUM) #1 for ADC2, 0 for ADC1
    xem.SelectFakeADC(0) #to deselect the fake ADC
    
    ## Disable pattern generator
    xem.EnablePgen(0)
    ## Reset the pipe FIFO
    xem.ResetFifo()
    ## Enable pipe transfers
    xem.EnablePipeTransfer(1)
    ## Start an acquisition
    xem.StartAcq()
    # Get one frame
    byte_data = bytearray(128*128*2*2)
    nbytes = xem.GetPipeData(byte_data)
    xem.Close()
    
    # write to file
    f = open(file_name, "wb")
    f.write(byte_data)
    f.close()
    #print("Wrote data to " + file_name)
    return byte_data

#acquire single frame
#ADCNUM is 0 or 1
#file_name is the file name for the saved dat file
def acqSingleFrameNoOpenClose(xem, ADCNUM, file_name):
    #xem.Open()
    # Acquire a frame
    ## Select ADC 2 and make sure the fake ADC is not selected
    xem.SelectADC(ADCNUM) #1 for ADC2, 0 for ADC1
    xem.SelectFakeADC(0) #to deselect the fake ADC --> negligible impact on frame rate
    
    ## Disable pattern generator
    xem.EnablePgen(0) #negligible impact on frame rate
    ## Reset the pipe FIFO
    xem.ResetFifo()
    ## Enable pipe transfers
    xem.EnablePipeTransfer(1)
    ## Start an acquisition
    xem.StartAcq()
    # Get one frame
    byte_data = bytearray(128*128*2*2)
    nbytes = xem.GetPipeData(byte_data)
    #xem.Close()
    
    
    
    # write to file
    f = open(file_name, "wb")
    f.write(byte_data)
    f.close()
    #print("Wrote data to " + file_name)
    return byte_data

#save settings_file
def saveSettingsFile(savedirname,bit_file_name,freq,OUTEN,PSET,term_count,TX_SWITCH_EN_SETTINGS,PULSE_AND_SETTINGS,RX_SWITCH_EN_SETTINGS,GLOB_EN_SETTINGS,LO_CTRL_SETTINGS,ADC_CAP_SETTINGS,DAC_VOLTAGE,ADC_TO_USE):
    
    from datetime import datetime
    now = datetime.now()
    dt_string = now.strftime("%m/%d/%Y %H:%M:%S")
    
    settings_file_name = savedirname + "settings.txt"
    
    # write to file
    f = open(settings_file_name, "w")
    f.write("date M/D/Y and time H/M/S = " + dt_string +"\n")
    
    f.write("Bit File Name: "+ bit_file_name +"\n") #write bit file name
    f.write("Frequency: "+str(freq)+" MHz"+"\n") #Frequency
    f.write("OUTEN: "+ str(OUTEN)+"\n")
    f.write("PSET: " + str(PSET)+"\n")
    f.write("Term Count: " + str(term_count)+"\n")
    f.write("TX_SWITCH_EN Settings: "+str(TX_SWITCH_EN_SETTINGS)+"\n")
    f.write("PULSE_AND Settings: " + str(PULSE_AND_SETTINGS)+"\n")
    f.write("RX_SWITCH_EN Settings: " + str(RX_SWITCH_EN_SETTINGS)+"\n")
    f.write("GLOB_EN Settings: " + str(GLOB_EN_SETTINGS)+"\n")
    f.write("LO_CTRL Settings: " + str(LO_CTRL_SETTINGS)+"\n")
    f.write("ADC_CAP Settings: " + str(ADC_CAP_SETTINGS)+"\n")
    f.write("DAC Voltage for All Pixels: " + str(DAC_VOLTAGE)+"\n")
    f.write("ADC Used: " + str(ADC_TO_USE)+"\n")
    
    f.close()
    print("Wrote data to " + settings_file_name)


#set up DAC to be the same for all pixels
def setAllPixSameDAC(xem,DAC_VOLTAGE):
    myDACVal = convertVoltToDAC(DAC_VOLTAGE)
    for row in range(128):
        print("loading DAC ROW (",row,") of 128")
        for col in range(128):
            for i_or_q in range(2):
                #print("loading DAC entry (",row,col,i_or_q,")") #if you want to print per pixel
                xem.LoadDACEntry(row, col, i_or_q, myDACVal) 
    print("Done loading DAC table")

#configure timing registers
def configTiming(xem,term_count,TX_SWITCH_EN_SETTINGS,PULSE_AND_SETTINGS,RX_SWITCH_EN_SETTINGS,GLOB_EN_SETTINGS,LO_CTRL_SETTINGS,ADC_CAP_SETTINGS):
    xem.SetTerminalCount(term_count) 
    xem.SetTiming(*((0,)+TX_SWITCH_EN_SETTINGS))   # TX_SWITCH_EN
    xem.SetTiming(*((1,)+PULSE_AND_SETTINGS) )   # PULSE_AND
    xem.SetTiming(*((2,)+RX_SWITCH_EN_SETTINGS))    # RX_SWITCH_EN
    xem.SetTiming(*((3,)+GLOB_EN_SETTINGS))    # GLOB_EN
    xem.SetTiming(*((4,)+LO_CTRL_SETTINGS))     # LO_CTRL
    xem.SetTiming(*((5,)+ADC_CAP_SETTINGS))  # ADC_CAPTURE #80 81


"""

freq ==> frequency in MHz --> resolution of 0.1MHz
OUTEN--> output enable-->0 for disable, 1 for enable
PSET --> select RF output power

power settings for PSET
0 --> Enabled, -4 dbm
1 --> Enabled, -1 dbm
2 --> Enabled, +2 dbm
3 --> Enabled, +5 dbm
don't use 2 or 3 unless really needed
"""
#configure VCO
def configureVCO(xem,freq,OUTEN,PSET):
    R0, R1, R2, R3, R4, R5 = calc_vco_reg_values(freq,OUTEN,PSET)
    #configure VCO registers on FPGA
    setXEMVCORegs(xem, R0, R1, R2, R3, R4, R5)

#configure VCO
def configureVCO_10khz(xem,freq,OUTEN,PSET):
    R0, R1, R2, R3, R4, R5 = calc_vco_reg_values_10khz(freq,OUTEN,PSET)
    #configure VCO registers on FPGA
    setXEMVCORegs(xem, R0, R1, R2, R3, R4, R5)
    
#convert raw ADC data to bit-shift corrected ADC data and convert to voltage
def convertADCToVolts(I_IMAGE, Q_IMAGE):
    I_IMAGE_ADC = I_IMAGE/16 #correct bit shift
    Q_IMAGE_ADC = Q_IMAGE/16 #correct bit shift
    I_IMAGE_VOLTS = I_IMAGE_ADC*1e-3 #convert to volts
    Q_IMAGE_VOLTS = Q_IMAGE_ADC*1e-3 #convert to volts
    return I_IMAGE_ADC, Q_IMAGE_ADC, I_IMAGE_VOLTS, Q_IMAGE_VOLTS


#take raw byte_data and convert to ADC output (bit shift is NOT corrected)
def convertToIQImage(byte_data):
    import numpy as np
    wi = 0
    imgBytesI = np.zeros(128*128)
    imgBytesQ = np.zeros(128*128)
    for row in range (128):
        for col in range(128):
            wi = row*128 + col
            iwrd = (byte_data[4 * wi + 0] + 256*byte_data[4 * wi + 1])
            qwrd = (byte_data[4 * wi + 2] + 256*byte_data[4 * wi + 3])
            imgBytesI[wi] = iwrd
            imgBytesQ[wi] = qwrd
            
            
            
    J_MYIMAGE_I=imgBytesI.reshape([128,128])
    J_MYIMAGE_Q=imgBytesQ.reshape([128,128])
    return J_MYIMAGE_I, J_MYIMAGE_Q


#convert voltage to DAC value (for xem7305.bit)
def convertVoltToDAC(myVolt):
    import math
    myDACVal = (myVolt-2.9622)*(512/(-0.33))
    myDACVal = math.floor(myDACVal)
    return myDACVal

#set VCO registers
def setXEMVCORegs(xem, R0, R1, R2, R3, R4, R5 ):
    xem.SetRegField(xem.spi_wdata, R5)
    xem.SetRegField(xem.vco_spi_go, 1)
    xem.SetRegField(xem.spi_wdata, R4)
    xem.SetRegField(xem.vco_spi_go, 1)
    xem.SetRegField(xem.spi_wdata, R3)
    xem.SetRegField(xem.vco_spi_go, 1)
    xem.SetRegField(xem.spi_wdata, R2)
    xem.SetRegField(xem.vco_spi_go, 1)
    xem.SetRegField(xem.spi_wdata, R1)
    xem.SetRegField(xem.vco_spi_go, 1)
    xem.SetRegField(xem.spi_wdata, R0)
    xem.SetRegField(xem.vco_spi_go, 1)


"""

freq_des ==> frequency in MHz --> resolution of 0.1MHz
OUTEN--> output enable-->0 for disable, 1 for enable
PSET --> select RF output power

power settings for PSET
0 --> Enabled, -4 dbm
1 --> Enabled, -1 dbm
2 --> Enabled, +2 dbm
3 --> Enabled, +5 dbm
don't use 2 or 3 unless really needed
"""

def calc_vco_reg_values(freq_des_user,OUTEN_user,PSET_user):
    import math
    
    freq_des = freq_des_user
    OUTEN = OUTEN_user
    PSET = PSET_user
    #keep OUTEN in bounds
    if (OUTEN > 1):
        OUTEN = 0
    #keep PSET in bounds
    if (PSET > 3):
        PSET = 0
    
    #this is fixed, not user specifiable
    freq_res = 0.1 # in MHz
    
    #make sure it is in the correct resolution
    freq_actual = freq_res * round(freq_des / freq_res)
    
    #calculate divider setting
    myDIVSEL = math.ceil(math.log(math.ceil(2200/freq_actual))/math.log(2))
    myDIV = 2**(myDIVSEL);
    
    #reference oscillator
    refin = 10 # in MHz
    #VCO PFD (phase frequency detector) frequency
    myPFD = 10 # in MHz
    
    mylumped = freq_actual*myDIV/myPFD #N in the ADI software
    
    myINT = math.floor(mylumped)
    
    #mod goes from 2 to 4095
    #frac goes from 0 to mod-1
    #if 0 for frac, use 2 for mod
    
    #MOD = Refin/Fres
    #fdes_dec = freq_actual - math.floor(freq_actual)
    if ((mylumped - myINT) == 0):
        myMOD = 2
        myFRAC = 0
    else:
        myMOD = refin/freq_res
        myFRAC = myMOD * (mylumped-math.floor(mylumped))
        myMOD = round(myMOD) #if some decimal stuff left
        myFRAC = round(myFRAC)
        
        while(math.gcd(myMOD,myFRAC)>1):
            mygcd = math.gcd(myMOD,myFRAC)
            myMOD = round(myMOD/mygcd)
            myFRAC = round(myFRAC/mygcd)
        
    #structure of register 0
    #0 at db31, 16 bit INT, 12 bit FRAC, 3 control bits 000
    reg0 = (myFRAC*(2**3)) + (myINT*(2**15))
    #structure of register 1
    reg1 = 0x8008001  + (myMOD * (2**3))
    
    #calculate reg4
    reg4 = (2**23) #fundamental feedback select
    reg4 = reg4 + (myDIVSEL*(2**20)) #divider select
    reg4 = reg4 + (2**2) #control bits
    reg4 = reg4 + (PSET*(2**3)) #power setting
    reg4 = reg4 + (OUTEN*(2**5)) #output enable setting
    reg4 = reg4 + ((80)*(2**12)) #band select clock divider value
    #registers that are unchanged
    reg2 = 0x4E42
    reg3 = 0x4B3
    reg5 = 0x580005

    return reg0, reg1, reg2, reg3, reg4, reg5

def calc_vco_reg_values_10khz(freq_des_user,OUTEN_user,PSET_user):
    import math
    
    freq_des = freq_des_user
    OUTEN = OUTEN_user
    PSET = PSET_user
    #keep OUTEN in bounds
    if (OUTEN > 1):
        OUTEN = 0
    #keep PSET in bounds
    if (PSET > 3):
        PSET = 0
    
    #this is fixed, not user specifiable
    freq_res = 0.01 # in MHz
    
    #make sure it is in the correct resolution
    freq_actual = freq_res * round(freq_des / freq_res)
    
    #calculate divider setting
    myDIVSEL = math.ceil(math.log(math.ceil(2200/freq_actual))/math.log(2))
    myDIV = 2**(myDIVSEL);
    
    #reference oscillator
    refin = 10 # in MHz
    #VCO PFD (phase frequency detector) frequency
    myPFD = 10 # in MHz
    
    mylumped = freq_actual*myDIV/myPFD #N in the ADI software
    
    myINT = math.floor(mylumped)
    
    #mod goes from 2 to 4095
    #frac goes from 0 to mod-1
    #if 0 for frac, use 2 for mod
    
    #MOD = Refin/Fres
    #fdes_dec = freq_actual - math.floor(freq_actual)
    if ((mylumped - myINT) == 0):
        myMOD = 2
        myFRAC = 0
    else:
        myMOD = refin/freq_res
        myFRAC = myMOD * (mylumped-math.floor(mylumped))
        myMOD = round(myMOD) #if some decimal stuff left
        myFRAC = round(myFRAC)
        
        while(math.gcd(myMOD,myFRAC)>1):
            mygcd = math.gcd(myMOD,myFRAC)
            myMOD = round(myMOD/mygcd)
            myFRAC = round(myFRAC/mygcd)
        
    #structure of register 0
    #0 at db31, 16 bit INT, 12 bit FRAC, 3 control bits 000
    reg0 = (myFRAC*(2**3)) + (myINT*(2**15))
    #structure of register 1
    reg1 = 0x8008001  + (myMOD * (2**3))
    
    #calculate reg4
    reg4 = (2**23) #fundamental feedback select
    reg4 = reg4 + (myDIVSEL*(2**20)) #divider select
    reg4 = reg4 + (2**2) #control bits
    reg4 = reg4 + (PSET*(2**3)) #power setting
    reg4 = reg4 + (OUTEN*(2**5)) #output enable setting
    reg4 = reg4 + ((80)*(2**12)) #band select clock divider value
    #registers that are unchanged
    reg2 = 0x4E42
    reg3 = 0x4B3
    reg5 = 0x580005

    return reg0, reg1, reg2, reg3, reg4, reg5
