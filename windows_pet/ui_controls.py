"""Consistent dropdowns that do not paint a native square Windows arrow."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QComboBox


class RoundedComboBox(QComboBox):
    def paintEvent(self, event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius=min(12,(self.height()-2)/2)
        painter.setPen(QPen(QColor('#3685AE' if self.hasFocus() else '#CAE2F0'),1.5))
        painter.setBrush(QColor('#EAF5FC' if self.isEnabled() else '#EDF1F4'))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1,1,-1,-1),radius,radius)
        arrow=QRectF(self.width()-28,3,24,self.height()-6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#D9EFFB' if self.isEnabled() else '#E2EBF0'))
        painter.drawRoundedRect(arrow,arrow.height()/2,arrow.height()/2)
        painter.setPen(QColor('#203E55' if self.isEnabled() else '#758692'))
        text_rect=self.rect().adjusted(10,0,-33,0)
        label=self.fontMetrics().elidedText(self.currentText(),Qt.TextElideMode.ElideRight,max(0,text_rect.width()))
        painter.drawText(text_rect,Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,label)
        center=arrow.center()
        pen=QPen(QColor('#49718A' if self.isEnabled() else '#91A7B4'),1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        path=QPainterPath()
        path.moveTo(center.x()-3,center.y()-1)
        path.lineTo(center.x(),center.y()+2)
        path.lineTo(center.x()+3,center.y()-1)
        painter.drawPath(path)

    def sizeHint(self):
        size=super().sizeHint()
        size.setWidth(size.width()+12)
        size.setHeight(max(26,size.height()))
        return size

    def showPopup(self):
        # Keep full option labels available even when the closed control elides.
        width=max([self.width(),*[self.fontMetrics().horizontalAdvance(self.itemText(i))+44
                                for i in range(self.count())]])
        if self.screen():width=min(width,self.screen().availableGeometry().width()-16)
        self.view().setMinimumWidth(width)
        super().showPopup()
