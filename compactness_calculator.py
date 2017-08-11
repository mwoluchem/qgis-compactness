# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CompactnessCalculator
                                 A QGIS plugin
 Compactness calculations
                              -------------------
        begin                : 2017-08-10
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Ariel and Vanessa
        email                : vanessa@flippable.org
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from PyQt4.QtCore import (QSettings, QTranslator, qVersion, QCoreApplication,
                          QVariant, QObject, SIGNAL)
from PyQt4.QtGui import QAction, QIcon, QMessageBox
from qgis.core import (QgsCoordinateTransform, QgsCoordinateReferenceSystem,
                       QgsFeature, QgsVectorLayer, QgsField, QgsMapLayerRegistry)
# Initialize Qt resources from file resources.py
import resources
# Import the code for the dialog
from compactness_calculator_dialog import CompactnessCalculatorDialog
import os.path
import json
from mander import districts, metrics, utils


class CompactnessCalculator:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'CompactnessCalculator_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)


        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&Compactness Calculator')
        # TODO: We are going to let the user set this up in a future iteration
        self.toolbar = self.iface.addToolBar(u'CompactnessCalculator')
        self.toolbar.setObjectName(u'CompactnessCalculator')

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('CompactnessCalculator', message)


    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        # Create the dialog (after translation) and keep reference
        self.dlg = CompactnessCalculatorDialog()

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToVectorMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/plugins/CompactnessCalculator/icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u'Compactness Calculations'),
            callback=self.run,
            parent=self.iface.mainWindow())

        QObject.connect(self.dlg.ConvexHull, SIGNAL("currentIndexChanged(int)"), self.populate)
        QObject.connect(self.dlg.polsby, SIGNAL("currentIndexChanged(int)"), self.populate)
        QObject.connect(self.dlg.Reock, SIGNAL("currentIndexChanged(int)"), self.populate)
        QObject.connect(self.dlg.Schwartzberg, SIGNAL("currentIndexChanged(int)"), self.populate)


    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginVectorMenu(
                self.tr(u'&Compactness Calculator'),
                action)
            self.iface.removeToolBarIcon(action)
        # remove the toolbar
        del self.toolbar


    def get_current_selection(self):
        """Returns the features currently selected by the user. Requires
        exactly one selection."""
        layer = self.iface.activeLayer()

        if not layer:
            QMessageBox.critical(self.dlg, 'Error', u"Please select a layer!")
            return False
        if len(layer.selectedFeatures()) != 1:
            QMessageBox.critical(self.dlg,
                                 'Error',
                                 u"Please select exactly one feature!")
            return False
        else:
            self.feature = layer.selectedFeatures()[0]
            self.crs = layer.crs()
            return True


    def feature_to_geojson(self):
        """Converts a qgis Feature geometry to GeoJSON format."""
        # Coordinate transform -> EPSG 2163
        target_crs = QgsCoordinateReferenceSystem(2163, QgsCoordinateReferenceSystem.EpsgCrsId)
        if not target_crs.isValid():
            QMessageBox.critical(self.dlg, 'Error', u"Error creating target CRS")
            return False

        xform = QgsCoordinateTransform(self.crs, target_crs)

        geom = self.feature.geometry()
        result = geom.transform(xform)
        if result != 0:
            QMessageBox.critical(self.dlg, 'Error', u"Error transforming CRS")
            return False

        # Save relevant params
        self.perimeter = geom.length()
        self.area = geom.area()
        self.convex_hull_area = geom.convexHull().area()
        # We can't calculate minimum bounding circle easily. Maybe calculate
        # largest distance from centroid to edge?

        # Put the QGIS geometry into a GeoJSON feature
        # TODO attach QGIS attributes -> GeoJSON feature properties
        # TODO handle more than one feature        
        f = {'geometry': json.loads(geom.exportToGeoJSON()),
             'properties': {},
             'type': 'Feature'}
        self.geojson = {'type': 'FeatureCollection',
                        'features': [f]}
        return True

    def calc_scores(self, mets):
        """Calculates compactness metrics for the geom using mander"""
        d = districts.District(json=self.geojson)
        print d.gdf.head()
        print d.area, d.perimeter, d.epsg
        self.scores = {}
        for metric in mets:
            if metric == "PP":
                self.scores[metric] = metrics.calculatePolsbyPopper(d)
            elif metric == "CH":
                self.scores[metric] = metrics.calculateConvexHull(d)
            elif metric == "RK":
                self.scores[metric] = metrics.calculateReock(d)
            elif metric == "SB":
                self.scores[metric] = metrics.calculateSchwartzberg(d)        
 
        return True

    def add_layer_to_ui(self):
        """Creates a layer and adds it to the current UI."""
        geom_type = self.geojson['features'][0].get('type', 'Polygon')  # Polygon, MultiPolygon, etc.

        # Create a new layer in memory
        new_layer = QgsVectorLayer(geom_type, "compactness_scores", "memory")
        provider = new_layer.dataProvider()

        attributes = self.feature.attributes()  # list of values
        fields = self.feature.fields()  # QgsFields object
        
        # Append new fields and attributes
        for score in self.scores:
            fields.append(QgsField(score, QVariant.Double, '', 20, 3))
            attributes.append(self.scores[score])
       
        new_layer.startEditing()

        provider.addAttributes(fields)
        new_layer.updateFields()

        f = QgsFeature()
        f.setGeometry(self.feature.geometry())
        f.setAttributes(attributes)
        provider.addFeatures([f])
        
        new_layer.commitChanges()
        new_layer.updateExtents()
        QgsMapLayerRegistry.instance().addMapLayer(new_layer)

        return True

    def save_to_geojson(self, path):
        """Saves the GeoJSON coordinates to disk."""

        with open(path, 'w') as fout:
            json.dump(self.geojson)
        return True

    # def run(self):
    #     layer = self.iface.activeLayer()

    #     # layer must be activated
    #     if not layer:
    #         QMessageBox.critical(self.dlg, 'Error', u'Please select layer!')
    #         return


    #     # >= 1 feature must be selected
    #     if len(layer.selectedFeatures()) != 1:
    #         QMessageBox.critical(self.dlg, 'Error', u'Please select exactly one feature!')
    #         return
    #     else:
    #         self.dlg.show()
    #         self.feature = layer.selectedFeatures()[0]
    #         self.qgscrs = layer.crs()
    #         self.populate()


    def run(self):
        """Run method that performs all the real work"""
        if not self.get_current_selection():
            return

        # show the dialog
        self.dlg.show()
        # Run the dialog event loop
        result = self.dlg.exec_()
        self.populate()
        # See if OK was pressed
        if result:
            self.feature_to_geojson()
            if not isinstance(self.geojson, dict):
                QMessageBox.critical(self.dlg, 'Error', u"GeoJSON wasn't formed properly.")
                return
            
            # Get desired metrics from dialog
            mets = ["PP"]
            if not self.calc_scores(mets):
                QMessageBox.critical(self.dlg, 'Error', u"Error calculating scores")
                return

            if not self.add_layer_to_ui():
                QMessageBox.critical(self.dlg, 'Error', u"Error adding layer to UI")
                return
            print self.scores
            return

    def populate(self):

        if self:
            # conversion
            print self.dlg.ConvexHull.isChecked()
            print self.dlg.polsby.isChecked()
            print self.dlg.Reock.isChecked()
            print self.dlg.Schwartzberg.isChecked()

