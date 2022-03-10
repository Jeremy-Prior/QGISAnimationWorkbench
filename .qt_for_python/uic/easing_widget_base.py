# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file '/home/timlinux/dev/python/QGISAnimationWorkbench/ui/easing_widget_base.ui'
#
# Created by: PyQt5 UI code generator 5.15.6
#
# WARNING: Any manual changes made to this file will be lost when pyuic5 is
# run again.  Do not edit this file unless you know what you are doing.


from PyQt5 import QtCore, QtGui, QtWidgets


class Ui_Form(object):
    def setupUi(self, Form):
        Form.setObjectName("Form")
        Form.resize(327, 245)
        self.gridLayout = QtWidgets.QGridLayout(Form)
        self.gridLayout.setObjectName("gridLayout")
        self.enable_easing = QtWidgets.QCheckBox(Form)
        self.enable_easing.setObjectName("enable_easing")
        self.gridLayout.addWidget(self.enable_easing, 0, 0, 1, 1)
        self.easing_combo = QtWidgets.QComboBox(Form)
        self.easing_combo.setEnabled(False)
        self.easing_combo.setObjectName("easing_combo")
        self.gridLayout.addWidget(self.easing_combo, 1, 0, 1, 1)
        self.easing_preview = QtWidgets.QWidget(Form)
        self.easing_preview.setMinimumSize(QtCore.QSize(250, 150))
        self.easing_preview.setObjectName("easing_preview")
        self.gridLayout.addWidget(self.easing_preview, 2, 0, 1, 1)

        self.retranslateUi(Form)
        QtCore.QMetaObject.connectSlotsByName(Form)

    def retranslateUi(self, Form):
        _translate = QtCore.QCoreApplication.translate
        Form.setWindowTitle(_translate("Form", "Form"))
        self.enable_easing.setText(_translate("Form", "Enable Easing"))
        self.easing_combo.setToolTip(_translate("Form", "The pan easing will determine the motion \n"
"characteristics of the camera on the Y axis \n"
"as it flies across the scene."))
