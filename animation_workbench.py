# coding=utf-8
"""This module contains the main GUI interaction logic for AnimationWorkbench."""

__copyright__ = "Copyright 2022, Tim Sutton"
__license__ = "GPL version 3"
__email__ = "tim@kartoza.com"
__revision__ = '$Format:%H$'

# This will make the QGIS use a world projection and then move the center
# of the CRS sequentially to create a spinning globe effect
from doctest import debug_script
import os
import timeit
import time
import subprocess

# This import is to enable SIP API V2
# noinspection PyUnresolvedReferences
import qgis  # NOQA

from qgis.PyQt import QtGui, QtWidgets
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtCore import QUrl
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtWidgets import QPushButton, QStyle, QVBoxLayout
from qgis.PyQt.QtGui import QImage, QPainter
from qgis.PyQt.QtCore import QEasingCurve, QPropertyAnimation, QPoint
from qgis.core import (
    QgsPointXY,
    QgsExpressionContextUtils,
    QgsProject,
    QgsExpressionContextScope,
    QgsMapRendererTask,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsMapRendererCustomPainterJob,
    QgsMapLayerProxyModel)
from qgis.PyQt.QtWidgets import QMessageBox, QPushButton
from qgis.core import Qgis
from .settings import set_setting, setting
from .utilities import get_ui_class, which, resources_path 
from enum import Enum

class MapMode(Enum):
    SPHERE = 1 # CRS will be manipulated to create a spinning globe effect
    PLANAR = 2 # CRS will not be altered, extents will as we pan and zoom
    FIXED_EXTENT = 3 # EASING and ZOOM disabled, extent stays in place

FORM_CLASS = get_ui_class('animation_workbench_base.ui')


class AnimationWorkbench(QtWidgets.QDialog, FORM_CLASS):
    """Dialog implementation class Animation Workbench class."""

    def __init__(self, parent=None, iface=None, dock_widget=None):
        """Constructor for the multi buffer dialog.

        :param parent: Parent widget of this dialog.
        :type parent: QWidget
        """
        QtWidgets.QDialog.__init__(self, parent)
        self.setupUi(self)        
        # Work around for not being able to set the layer
        # types allowed in the QgsMapLayerSelector combo
        # See https://github.com/qgis/QGIS/issues/38472#issuecomment-715178025
        self.layer_combo.setFilters(QgsMapLayerProxyModel.PointLayer)

        self.setWindowTitle(self.tr('Animation Workbench'))
        icon = resources_path(
            'img', 'icons', 'animation-workshop.svg')
        self.setWindowIcon(QtGui.QIcon(icon))
        self.parent = parent
        self.iface = iface
        # Set up things for context help
        self.help_button = self.button_box.button(
            QtWidgets.QDialogButtonBox.Help)
        # Allow toggling the help button
        self.help_button.setCheckable(True)
        self.help_button.toggled.connect(self.help_toggled)

        # Close button action
        close_button = self.button_box.button(
            QtWidgets.QDialogButtonBox.Close)
        close_button.clicked.connect(self.reject)
        close_button.clicked.connect(self.reject)
        # Fix ends
        ok_button = self.button_box.button(QtWidgets.QDialogButtonBox.Ok)
        #ok_button.clicked.connect(self.accept)
        ok_button.setText('Run')
        
        # How many frames to render for each point pair transition
        # The output is generated at 30fps so choosing 30
        # would fly to each point for 1s
        # You can then use the 'current_point' project variable
        # to determine the current point id
        # and the 'point_frame' project variable to determine
        # the frame number for the current point based on frames_for_interval
        
        self.frames_per_point = int(
            setting(key='frames_per_point', default='90'))
        self.point_frames_spin.setValue(self.frames_per_point)

        # How many frames to dwell at each point for (output at 30fps)
        self.dwell_frames = int(
            setting(key='dwell_frames', default='30'))
        self.hover_frames_spin.setValue(self.dwell_frames)
        # How many frames to render when we are in static mode
        self.frames_for_extent = int(
            setting(key='frames_for_extent', default='90'))
        self.extent_frames_spin.setValue(self.frames_for_extent)
        # Keep the scales the same if you dont want it to zoom in an out
        self.max_scale = int(setting(key='max_scale', default='10000000'))
        self.scale_range.setMaximumScale(self.max_scale)
        self.min_scale = int(setting(key='min_scale', default='25000000'))
        self.scale_range.setMinimumScale(self.min_scale)
        self.image_counter = None 
        # enable this if you want wobbling panning
        if setting(key='enable_pan_easing', default='false') == 'false':
            self.enable_pan_easing.setChecked(False)
        else:
            self.enable_pan_easing.setChecked(True)
        # enable this if you want wobbling zooming
        if setting(key='enable_pan_easing', default='false') == 'false':
            self.enable_zoom_easing.setChecked(False)
        else:
            self.enable_zoom_easing.setChecked(True)            
        self.previous_point = None

        QgsExpressionContextUtils.setProjectVariable(
            QgsProject.instance(), 'frames_per_point', 0)
        QgsExpressionContextUtils.setProjectVariable(
            QgsProject.instance(), 'current_frame', 0)
        QgsExpressionContextUtils.setProjectVariable(
            QgsProject.instance(), 'current_point_id', 0)
        # None, Panning, Hovering
        QgsExpressionContextUtils.setProjectVariable(
            QgsProject.instance(), 'current_animation_action', 'None')

        self.map_mode = None
        mode_string = setting(key='map_mode',default='sphere')
        if mode_string == 'sphere':
            self.map_mode == MapMode.SPHERE
            self.radio_sphere.setChecked(True)
            self.status_stack.setCurrentIndex(0)
            self.settings_stack.setCurrentIndex(0)
        elif mode_string == 'planar':
            self.map_mode == MapMode.PLANAR
            self.radio_planar.setChecked(True)
            self.status_stack.setCurrentIndex(0)
            self.settings_stack.setCurrentIndex(0)
        else:
            self.map_mode == MapMode.FIXED_EXTENT
            self.radio_extent.setChecked(True)
            self.status_stack.setCurrentIndex(1)
            self.settings_stack.setCurrentIndex(1)

        self.radio_planar.toggled.connect(
            self.show_non_fixed_extent_settings
        )
        self.radio_sphere.toggled.connect(
            self.show_non_fixed_extent_settings
        )
        self.radio_extent.toggled.connect(
            self.show_fixed_extent_settings
        )

        # Setup easing combos and previews etc
        self.load_combo_with_easings(self.pan_easing_combo)
        self.load_combo_with_easings(self.zoom_easing_combo)
        self.setup_easing_previews()

        self.pan_easing = None
        pan_easing_index = int(setting(key='pan_easing', default='0'))
        
        self.zoom_easing = None
        zoom_easing_index = int(setting(key='zoom_easing', default='0'))

        # Keep this after above animations are set up 
        # since the slot requires the above setup to be completed
        self.pan_easing_combo.currentIndexChanged.connect(
            self.pan_easing_changed)
        self.zoom_easing_combo.currentIndexChanged.connect(
            self.zoom_easing_changed)

        # Update the gui
        self.pan_easing_combo.setCurrentIndex(pan_easing_index)
        self.zoom_easing_combo.setCurrentIndex(zoom_easing_index)
        # The above doesnt trigger the slots which we need to do 
        # to populate the easing class members, so call explicitly
        self.pan_easing_changed(pan_easing_index)
        self.zoom_easing_changed(zoom_easing_index)

        # Set an initial image in the preview based on the current map
        image = self.render_image()
        pixmap = QtGui.QPixmap.fromImage(image)
        self.current_frame_preview.setPixmap(pixmap)
        # The maximum number of concurrent threads to allow
        # during rendering. Probably setting to the same number 
        # of CPU cores you have would be a good conservative approach
        # You could probably run 100 or more on a decently specced machine
        self.render_thread_pool_size = int(setting(
            key='render_thread_pool_size', default=100))
        # A list of tasks that need to be rendered but
        # cannot be because the job queue is too full.
        # we pop items off this list self.render_thread_pool_size
        # at a time whenver the task manager tells us the queue is
        # empty.
        self.renderer_queue = []
        # Queue manager for above.
        QgsApplication.taskManager().allTasksFinished.connect(
            self.process_more_tasks)

        self.progress_bar.setValue(0)
        # This will be half the number of frames per point
        # so that the first half of the journey is flying up
        # away from the last point and the next half of the
        # journey is flying down towards the next point.
        self.frames_to_zenith = None

        reuse_cache = setting(key='reuse_cache', default='false')
        if  reuse_cache == 'false':
            self.reuse_cache.setChecked(False)
        else:
            self.reuse_cache.setChecked(True)

        # Video playback stuff - see bottom of file for related methods 
        self.media_player = QMediaPlayer(
            None, #.video_preview_widget, 
            QMediaPlayer.VideoSurface)
        video_widget = QVideoWidget()
        #self.video_page.replaceWidget(self.video_preview_widget,video_widget)
        self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_button.clicked.connect(self.play)
        self.media_player.setVideoOutput(video_widget)
        self.media_player.stateChanged.connect(self.media_state_changed)
        self.media_player.positionChanged.connect(self.position_changed)
        self.media_player.durationChanged.connect(self.duration_changed)
        self.media_player.error.connect(self.handle_video_error) 
        layout = QtWidgets.QGridLayout(self.video_preview_widget)
        layout.addWidget(video_widget)
        # Enable image preview page on startup
        self.preview_stack.setCurrentIndex(0)
        # Enable easing status page on startup
        self.status_stack.setCurrentIndex(0)
        QgsApplication.taskManager().progressChanged.connect(
            self.show_status)

    def show_non_fixed_extent_settings(self):
            
        self.settings_stack.setCurrentIndex(0)
        
    def show_fixed_extent_settings(self):
            
        self.settings_stack.setCurrentIndex(1)
                
    def show_status(self):
        """
        Display the size of the QgsTaskManager queue.

        :returns: None
        """
        size = QgsApplication.taskManager().count()
        self.queue_lcd.display(size)
        size = (
            QgsApplication.taskManager().count() -
            QgsApplication.taskManager().countActiveTasks())
        self.completed_lcd.display(size)
        size = QgsApplication.taskManager().countActiveTasks()
        self.active_lcd.display(size)
        
    def process_more_tasks(self):
        """
        Feed the QgsTaskManager with another bundle of tasks.

        This slot is called whenever the QgsTaskManager queue is 
        finished (by means of the 'allTasksFinished' signal).

        :returns: None
        """
            
        if len(self.renderer_queue) == 0:
            # all processing done so go off and generate
            # the vid or gif
            self.processing_completed()
        else:
            self.output_log_text_edit.append(
                'Thread pool emptied, adding more tasks')
            pop_size = self.render_thread_pool_size
            if len(self.renderer_queue) < pop_size:
                pop_size = len(self.renderer_queue)
            for task in range(0, pop_size):
                task_id = QgsApplication.taskManager().addTask(
                    self.renderer_queue.pop(0))

    def display_information_message_box(
            self, parent=None, title=None, message=None):
        """
        Display an information message box.
        :param title: The title of the message box.
        :type title: basestring
        :param message: The message inside the message box.
        :type message: basestring
        """
        QMessageBox.information(parent, title, message)

    def display_information_message_bar(
            self,
            title=None,
            message=None,
            more_details=None,
            button_text='Show details ...',
            duration=8):
        """
        Display an information message bar.
        :param title: The title of the message bar.
        :type title: basestring
        :param message: The message inside the message bar.
        :type message: basestring
        :param more_details: The message inside the 'Show details' button.
        :type more_details: basestring
        :param button_text: The text of the button if 'more_details' is not empty.
        :type button_text: basestring
        :param duration: The duration for the display, default is 8 seconds.
        :type duration: int
        """
        self.iface.messageBar().clearWidgets()
        widget = self.iface.messageBar().createMessage(title, message)

        if more_details:
            button = QPushButton(widget)
            button.setText(button_text)
            button.pressed.connect(
                lambda: self.display_information_message_box(
                    title=title, message=more_details))
            widget.layout().addWidget(button)

        self.iface.messageBar().pushWidget(widget, Qgis.Info, duration)

    def pan_easing_changed(self, index):
        """Handle changes to the pan easing type combo.
        
        .. note:: This is called on changes to the pan easing combo.

        .. versionadded:: 1.0

        :param index: Index of the now selected combo item.
        :type flag: int

        """
        easing_type = QEasingCurve.Type(index)
        self.pan_easing_preview_animation.setEasingCurve(easing_type)
        self.pan_easing = QEasingCurve(easing_type)

    def zoom_easing_changed(self, index):
        """Handle changes to the zoom easing type combo.
        
        .. note:: This is called on changes to the zoom easing combo.

        .. versionadded:: 1.0

        :param index: Index of the now selected combo item.
        :type flag: int

        """
        easing = QEasingCurve.Type(index)
        self.zoom_easing_preview_animation.setEasingCurve(easing)
        self.zoom_easing = QEasingCurve(easing)

    # Prevent the slot being called twize
    @pyqtSlot()
    def accept(self):
        """Process the animation sequence.

        .. note:: This is called on OK click.
        """
        # Image preview page
        self.preview_stack.setCurrentIndex(0)
        # Enable queue status page
        self.status_stack.setCurrentIndex(1)
        self.queue_lcd.display(0)
        self.active_lcd.display(0)
        self.completed_lcd.display(0)
        # set parameter from dialog

        if not self.reuse_cache.isChecked():
            os.system('rm /tmp/globe*')

        # Point layer that we will visit each point for
        point_layer = self.layer_combo.currentLayer()
        self.max_scale = self.scale_range.maximumScale()
        self.min_scale = self.scale_range.minimumScale()
        self.dwell_frames = self.hover_frames_spin.value()
        self.frames_per_point = self.point_frames_spin.value()
        self.frames_to_zenith = int(self.frames_per_point / 2)
        self.frames_for_extent = self.extent_frames_spin.value()
        self.image_counter = 1
        feature_count = point_layer.featureCount()

        if self.radio_sphere.isChecked():
            self.map_mode = MapMode.SPHERE
            set_setting(key='map_mode',value='sphere')
        elif self.radio_planar.isChecked():
            self.map_mode = MapMode.PLANAR
            set_setting(key='map_mode',value='planar')
        else:
            self.map_mode = MapMode.FIXED_EXTENT
            set_setting(key='map_mode',value='fixed_extent')
        # Save state
        set_setting(key='frames_per_point',value=self.frames_per_point)
        set_setting(key='dwell_frames',value=self.dwell_frames)
        set_setting(key='frames_for_extent',value=self.frames_for_extent)
        set_setting(key='max_scale',value=int(self.max_scale))
        set_setting(key='min_scale',value=int(self.min_scale))
        set_setting(key='enable_pan_easing',value=self.enable_pan_easing.isChecked())
        set_setting(key='enable_zoom_easing',value=self.enable_zoom_easing.isChecked())
        set_setting(key='pan_easing',value=self.pan_easing_combo.currentIndex())
        set_setting(key='zoom_easing',value=self.zoom_easing_combo.currentIndex())
        set_setting(
            key='render_thread_pool_size',value=self.render_thread_pool_size)
        set_setting(key='reuse_cache',value=self.reuse_cache.isChecked())
        
        if self.map_mode == MapMode.FIXED_EXTENT:
            self.output_log_text_edit.append(
                'Generating %d frames for fixed extent render' % self.frames_for_extent)
            self.progress_bar.setMaximum(self.frames_for_extent)
            self.progress_bar.setValue(0)
            self.image_counter = 0
            for image_count in range(0, self.frames_for_extent):
                name = ('/tmp/globe-%s.png' % str(self.image_counter).rjust(10, '0'))
                self.render_image_as_task(
                    name,
                    None,
                    self.image_counter,
                    'Fixed Extent'
                )
                self.progress_bar.setValue(self.image_counter)
                self.image_counter += 1
        else:
            # Subtract one because we already start at the first point
            total_frame_count = (feature_count - 1) * (self.dwell_frames + self.frames_per_point)
            self.output_log_text_edit.append('Generating %d frames' % total_frame_count)
            self.progress_bar.setMaximum(total_frame_count)
            self.progress_bar.setValue(0)
            self.previous_point = None
            for feature in point_layer.getFeatures():
                # None, Panning, Hovering
                if self.previous_point is None:
                    self.previous_point = feature
                    self.dwell_at_point(feature)
                else:
                    self.fly_point_to_point(self.previous_point, feature)
                    self.dwell_at_point(feature)
                    self.previous_point = feature        
    
    def processing_completed(self):
        """Run after all processing is done to generate gif or mp4.

        .. note:: This called my process_more_tasks when all tasks are complete.
        """
        if self.radio_gif.isChecked():
            self.output_log_text_edit.append('Generating GIF')
            convert = which('convert')[0]
            self.output_log_text_edit.append('convert found: %s' % convert)
            # Now generate the GIF. If this fails try run the call from the command line
            # and check the path to convert (provided by ImageMagick) is correct...
            # delay of 3.33 makes the output around 30fps               
            os.system('%s -delay 3.33 -loop 0 /tmp/globe-*.png /tmp/globe.gif' % convert)
            # Now do a second pass with image magick to resize and compress the
            # gif as much as possible.  The remap option basically takes the
            # first image as a reference inmage for the colour palette Depending
            # on you cartography you may also want to bump up the colors param
            # to increase palette size and of course adjust the scale factor to
            # the ultimate image size you want               
            os.system('%s /tmp/globe.gif -coalesce -scale 600x600 -fuzz 2% +dither -remap /tmp/globe.gif[20] +dither -colors 14 -layers Optimize /tmp/globe_small.gif' % (convert))
            # Video preview page
            self.preview_stack.setCurrentIndex(1)
            self.media_player.setMedia(
                QMediaContent(QUrl.fromLocalFile('/tmp/globe_small-gif')))
            self.play_button.setEnabled(True)
            self.play()
        else:
            self.output_log_text_edit.append('Generating MP4 Movie')
            ffmpeg = which('ffmpeg')[0]
            # Also we will make a video of the scene - useful for cases where
            # you have a larger colour pallette and gif will not hack it. The Pad
            # option is to deal with cases where ffmpeg complains because the h
            # or w of the image is an odd number of pixels.  :color=white pads
            # the video with white pixels. Change to black if needed.
            # -y to force overwrite exising file
            self.output_log_text_edit.append('ffmpeg found: %s' % ffmpeg)
            os.system('%s -y -framerate 30 -pattern_type glob -i "/tmp/globe-*.png" -vf "pad=ceil(iw/2)*2:ceil(ih/2)*2:color=white" -c:v libx264 -pix_fmt yuv420p /tmp/globe.mp4' % ffmpeg)
            # Video preview page
            self.preview_stack.setCurrentIndex(1)
            self.media_player.setMedia(
                QMediaContent(QUrl.fromLocalFile('/tmp/globe.mp4')))
            self.play_button.setEnabled(True)
            self.play()

            
    def render_image(self):
        """Render the current canvas to an image.
        
        .. note:: This is renders synchronously.

        .. versionadded:: 1.0

        :returns QImage: 
        """
        size = self.iface.mapCanvas().size()
        image = QImage(size, QImage.Format_RGB32)

        painter = QPainter(image)
        settings = self.iface.mapCanvas().mapSettings()
        self.iface.mapCanvas().refresh()
        # You can fine tune the settings here for different
        # dpi, extent, antialiasing...
        # Just make sure the size of the target image matches

        job = QgsMapRendererCustomPainterJob(settings, painter)
        job.renderSynchronously()
        painter.end()
        self.display_information_message_bar(
                title="Image rendered",
                message="Image rendered",
                more_details=None,
                button_text='Show details ...',
                duration=8)
        return image


    def render_image_to_file(self, name):
        size = self.iface.mapCanvas().size()
        image = QImage(size, QImage.Format_RGB32)

        painter = QPainter(image)
        settings = self.iface.mapCanvas().mapSettings()
        self.iface.mapCanvas().refresh()
        # You can fine tune the settings here for different
        # dpi, extent, antialiasing...
        # Just make sure the size of the target image matches

        job = QgsMapRendererCustomPainterJob(settings, painter)
        job.renderSynchronously()
        painter.end()
        image.save(name)


    def render_image_as_task(
        self,
        name,
        current_point_id,
        current_frame,
        action='None'):
           
        #size = self.iface.mapCanvas().size()
        settings = self.iface.mapCanvas().mapSettings()
        # The next part sets project variables that you can use in your 
        # cartography etc. to see the progress. Here is an example
        # of a QGS expression you can use in the map decoration copyright
        # widget to show current script progress
        # [%'Frame ' || to_string(coalesce(@current_frame, 0)) || '/' || 
        # to_string(coalesce(@frames_per_point, 0)) || ' for point ' || 
        # to_string(coalesce(@current_point_id,0))%]
        task_scope = QgsExpressionContextScope()
        task_scope.setVariable('current_point_id', current_point_id)
        task_scope.setVariable('frames_per_point', self.frames_per_point)
        task_scope.setVariable('current_frame', current_frame)        
        task_scope.setVariable('current_animation_action', action)        
        context = settings.expressionContext()
        context.appendScope(task_scope) 
        settings.setExpressionContext(context)
        # Set the output file name for the render task
        mapRendererTask = QgsMapRendererTask( settings, name, "PNG" )
        # We need to clone the annotations because otherwise SIP will 
        # pass ownership and then cause a crash when the render task is destroyed
        annotations = QgsProject.instance().annotationManager().annotations()
        annotations_list = [a.clone() for a in annotations]
        if (len(annotations_list) > 0):
            mapRendererTask.addAnnotations([a.clone() for a in annotations])
        # Add decorations to the render job
        decorations = self.iface.activeDecorations()
        mapRendererTask.addDecorations(decorations)

        # If we have reached the rendering pool cap, we will just keep 
        # this task in a separate queue and then pop them off the queue
        # self.render_thread_pool_size at a time whenver the task manager
        # lets us know we have nothing to do
        if QgsApplication.taskManager().countActiveTasks() > self.render_thread_pool_size:
            self.renderer_queue.append(mapRendererTask)
        else:
            # Start the rendering task on the queue
            task_id = QgsApplication.taskManager().addTask(mapRendererTask)

    def fly_point_to_point(self, start_point, end_point):
       
        self.image_counter += 1
        self.progress_bar.setValue(self.image_counter)
        x_min = start_point.geometry().asPoint().x()
        x_max = end_point.geometry().asPoint().x()
        x_range = abs(x_max - x_min)
        x_increment = x_range / self.frames_per_point
        y_min = start_point.geometry().asPoint().y()
        y_max = end_point.geometry().asPoint().y()
        y_range = abs(y_max - y_min)
        y_increment = y_range / self.frames_per_point
        # at the midpoint of the traveral between the two points
        # we switch the easing around so the movememnt first
        # goes away from the direct line, then towards it.
        y_midpoint = (y_increment * self.frames_per_point) / 2
        x_midpoint = (x_increment * self.frames_per_point) / 2
        scale = None

        for current_frame in range(0, self.frames_per_point, 1):

            # For x we could have a pan easing
            x_offset = x_increment * current_frame
            if self.enable_pan_easing.isChecked():
                if x_offset < x_midpoint:
                    # Flying away from centerline
                    # should be 0 at origin, 1 at centerpoint
                    pan_easing_factor = 1 - self.pan_easing.valueForProgress(
                        x_offset/x_midpoint)
                else:
                    # Flying towards centerline
                    # should be 1 at centerpoint, 0 at destination
                    try:
                        pan_easing_factor = self.pan_easing.valueForProgress(
                            (x_offset - x_midpoint) / x_midpoint)
                    except:
                        pan_easing_factor = 0
                x_offset = x_offset * pan_easing_factor
            # Deal with case where we need to fly west instead of east
            if x_min < x_max:
                x = x_min + x_offset
            else:
                x = x_min - x_offset

            # for Y we could have easing
            y_offset = y_increment * current_frame
            
            if self.enable_pan_easing.isChecked():
                if y_offset < y_midpoint:
                    # Flying away from centerline
                    # should be 0 at origin, 1 at centerpoint
                    pan_easing_factor = 1 - self.pan_easing.valueForProgress(
                        y_offset / y_midpoint)
                else:
                    # Flying towards centerline
                    # should be 1 at centerpoint, 0 at destination
                    pan_easing_factor = self.pan_easing.valueForProgress(
                        y_offset - y_midpoint / y_midpoint)
                
                y_offset = y_offset * pan_easing_factor
            
            # Deal with case where we need to fly north instead of south
            if y_min < y_max:
                y = y_min + y_offset
            else:
                y = y_min - y_offset

            # zoom in and out to each feature if we are 
            if self.enable_zoom_easing.isChecked():
                # Now use easings for zoom level too
                # first figure out if we are flying up or down
                if current_frame < self.frames_to_zenith:
                    # Flying up
                    zoom_easing_factor = 1- self.zoom_easing.valueForProgress(
                        current_frame/self.frames_to_zenith)
                    scale = ((self.max_scale - self.min_scale) * 
                              zoom_easing_factor) + self.min_scale
                else:
                    # flying down
                    zoom_easing_factor = self.zoom_easing.valueForProgress(
                        (current_frame - self.frames_to_zenith)/self.frames_to_zenith)
                    scale = ((self.max_scale - self.min_scale) * 
                        zoom_easing_factor) + self.min_scale

            if self.map_mode ==MapMode.PLANAR:
                self.iface.mapCanvas().setCenter(
                    QgsPointXY(x,y))
            if scale is not None:
                self.iface.mapCanvas().zoomScale(scale)

            # Change CRS if needed
            if self.map_mode == MapMode.SPHERE:
                definition = ( 
                '+proj=ortho +lat_0=%f +lon_0=%f +x_0=0 +y_0=0 +ellps=sphere +units=m +no_defs' % (x, y))
                crs = QgsCoordinateReferenceSystem()
                crs.createFromProj(definition)
                self.iface.mapCanvas().setDestinationCrs(crs)
                if not self.enable_zoom_easing.isChecked():
                    self.iface.mapCanvas().zoomToFullExtent()

            # Pad the numbers in the name so that they form a 10 digit string with left padding of 0s
            name = ('/tmp/globe-%s.png' % str(self.image_counter).rjust(10, '0'))
            starttime = timeit.default_timer()
            if os.path.exists(name) and self.reuse_cache.isChecked():
                # User opted to re-used cached images so do nothing for now
                pass
            else:
                # Not crashy but no decorations and annotations....
                #render_image(name)
                # crashy - check with Nyall why...
                self.render_image_as_task(
                    name, end_point.id(), current_frame, 'Panning')
            self.image_counter += 1
            self.progress_bar.setValue(self.image_counter)

    def load_image(self, name):
        #Load the preview with the named image file 
        with open(name, 'rb') as image_file:
            content = image_file.read()
            image = QtGui.QImage()
            image.loadFromData(content)
            pixmap = QtGui.QPixmap.fromImage(image)
            self.current_frame_preview.setPixmap(pixmap)

    def dwell_at_point(self, feature):
        #f.write('Render Time,Longitude,Latitude,Latitude Easing Factor,Zoom Easing Factor,Zoom Scale\n')
        x = feature.geometry().asPoint().x()
        y = feature.geometry().asPoint().y()
        point = QgsPointXY(x,y)
        self.iface.mapCanvas().setCenter(point)
        self.iface.mapCanvas().zoomScale(self.max_scale)

        for current_frame in range(0, self.dwell_frames, 1):
            # Pad the numbers in the name so that they form a 10 digit string with left padding of 0s
            name = ('/tmp/globe-%s.png' % str(self.image_counter).rjust(10, '0'))
            if os.path.exists(name) and self.reuse_cache.isChecked():
                # User opted to re-used cached images to do nothing for now
                self.load_image(name)
            else:
                # Not crashy but no decorations and annotations....
                #render_image_to_file(name)
                # crashy - check with Nyall why...
                self.render_image_as_task(
                    name, feature.id(), current_frame, 'Hovering')
            
            self.image_counter += 1
            self.progress_bar.setValue(self.image_counter)

    def help_toggled(self, flag):
        """Show or hide the help tab in the stacked widget.
        :param flag: Flag indicating whether help should be shown or hidden.
        :type flag: bool
        """
        if flag:
            self.help_button.setText(self.tr('Hide Help'))
            self.show_help()
        else:
            self.help_button.setText(self.tr('Show Help'))
            self.hide_help()

    def hide_help(self):
        """Hide the usage info from the user."""
        self.main_stacked_widget.setCurrentIndex(1)

    def show_help(self):
        """Show usage info to the user."""
        # Read the header and footer html snippets
        self.main_stacked_widget.setCurrentIndex(0)
        header = html_header()
        footer = html_footer()

        string = header

        message = multi_buffer_help()

        string += message.to_html()
        string += footer

        self.help_web_view.setHtml(string)
    
    def load_combo_with_easings(self, combo):
        # Perhaps we can softcode these items using the logic here
        # https://github.com/baoboa/pyqt5/blob/master/examples/animation/easing/easing.py#L159
        combo.addItem("Linear",QEasingCurve.Linear)
        combo.addItem("InQuad",QEasingCurve.InQuad)
        combo.addItem("OutQuad",QEasingCurve.OutQuad)
        combo.addItem("InOutQuad",QEasingCurve.InOutQuad)
        combo.addItem("OutInQuad",QEasingCurve.OutInQuad)
        combo.addItem("InCubic",QEasingCurve.InCubic)
        combo.addItem("OutCubic",QEasingCurve.OutCubic)
        combo.addItem("InOutCubic",QEasingCurve.InOutCubic)
        combo.addItem("OutInCubic",QEasingCurve.OutInCubic)
        combo.addItem("InQuart",QEasingCurve.InQuart)
        combo.addItem("OutQuart",QEasingCurve.OutQuart)
        combo.addItem("InOutQuart",QEasingCurve.InOutQuart)
        combo.addItem("OutInQuart",QEasingCurve.OutInQuart)
        combo.addItem("InQuint",QEasingCurve.InQuint)
        combo.addItem("OutQuint",QEasingCurve.OutQuint)
        combo.addItem("InOutQuint",QEasingCurve.InOutQuint)
        combo.addItem("OutInQuint",QEasingCurve.OutInQuint)
        combo.addItem("InSine",QEasingCurve.InSine)
        combo.addItem("OutSine",QEasingCurve.OutSine)
        combo.addItem("InOutSine",QEasingCurve.InOutSine)
        combo.addItem("OutInSine",QEasingCurve.OutInSine)
        combo.addItem("InExpo",QEasingCurve.InExpo)
        combo.addItem("OutExpo",QEasingCurve.OutExpo)
        combo.addItem("InOutExpo",QEasingCurve.InOutExpo)
        combo.addItem("OutInExpo",QEasingCurve.OutInExpo)
        combo.addItem("InCirc",QEasingCurve.InCirc)
        combo.addItem("OutCirc",QEasingCurve.OutCirc)
        combo.addItem("InOutCirc",QEasingCurve.InOutCirc)
        combo.addItem("OutInCirc",QEasingCurve.OutInCirc)
        combo.addItem("InElastic",QEasingCurve.InElastic)
        combo.addItem("OutElastic",QEasingCurve.OutElastic)
        combo.addItem("InOutElastic",QEasingCurve.InOutElastic)
        combo.addItem("OutInElastic",QEasingCurve.OutInElastic)
        combo.addItem("InBack",QEasingCurve.InBack)
        combo.addItem("OutBack",QEasingCurve.OutBack)
        combo.addItem("InOutBack",QEasingCurve.InOutBack)
        combo.addItem("OutInBack",QEasingCurve.OutInBack)
        combo.addItem("InBounce",QEasingCurve.InBounce)
        combo.addItem("OutBounce",QEasingCurve.OutBounce)
        combo.addItem("InOutBounce",QEasingCurve.InOutBounce)
        combo.addItem("OutInBounce",QEasingCurve.OutInBounce)
        combo.addItem("BezierSpline",QEasingCurve.BezierSpline)
        combo.addItem("TCBSpline",QEasingCurve.TCBSpline)
        combo.addItem("Custom",QEasingCurve.Custom)
    
    def setup_easing_previews(self):
        # Set up easing previews
        self.pan_easing_preview_icon = QtWidgets.QWidget(self.pan_easing_preview)
        self.pan_easing_preview_icon.setStyleSheet("background-color:yellow;border-radius:5px;")
        self.pan_easing_preview_icon.resize(10, 10)
        self.pan_easing_preview_animation = QPropertyAnimation(self.pan_easing_preview_icon, b"pos")
        self.pan_easing_preview_animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.pan_easing_preview_animation.setStartValue(QPoint(0, 0))
        self.pan_easing_preview_animation.setEndValue(QPoint(250, 150))
        self.pan_easing_preview_animation.setDuration(1500)
        # loop forever ...
        self.pan_easing_preview_animation.setLoopCount(-1)
        self.pan_easing_preview_animation.start()

        self.zoom_easing_preview_icon = QtWidgets.QWidget(self.zoom_easing_preview)
        self.zoom_easing_preview_icon.setStyleSheet("background-color:#005bbc;border-radius:5px;")
        self.zoom_easing_preview_icon.resize(10, 10)
        self.zoom_easing_preview_animation = QPropertyAnimation(self.zoom_easing_preview_icon, b"pos")
        self.zoom_easing_preview_animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.zoom_easing_preview_animation.setStartValue(QPoint(0, 0))
        self.zoom_easing_preview_animation.setEndValue(QPoint(250, 150))
        self.zoom_easing_preview_animation.setDuration(1500)
        # loop forever ...
        self.zoom_easing_preview_animation.setLoopCount(-1)
        self.zoom_easing_preview_animation.start()


    # Video Playback Methods
    def play(self):
        if self.media_player.state() == QMediaPlayer.PlayingState:
            self.media_player.pause()
        else:
            self.media_player.play()

    def media_state_changed(self, state):
        if self.media_player.state() == QMediaPlayer.PlayingState:
            self.play_button.setIcon(
                self.style().standardIcon(QStyle.SP_MediaPause))
        else:
            self.play_button.setIcon(
                self.style().standardIcon(QStyle.SP_MediaPlay))

    def position_changed(self, position):
        self.video_slider.setValue(position)

    def duration_changed(self, duration):
        self.video_slider.setRange(0, duration)

    def set_position(self, position):
        self.media_player.setPosition(position)
    
    def handle_video_error(self):
        self.play_button.setEnabled(False)
        self.output_log_text_edit.append(
            self.mediaPlayer.errorString())
