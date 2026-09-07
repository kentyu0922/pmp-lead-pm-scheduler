Attribute VB_Name = "AddResponsibilityColumns"
' ============================================================
'  add_responsibility_columns.bas
'  用途：在 MS Project 中一键把「执行单位 / 责任人 / 责任标识」
'        三列加入甘特图左侧任务表（新建「责任分工视图」并应用）。
'
'  何时需要本宏：
'    Python(COM) 渲染器已把这三列的数据写入任务的 Text1/Text2/Text3，
'    并自动改名为「执行单位/责任人/责任标识」。但部分中文版 MS Project
'    的 COM TableEditEx(Create=True) 受限、无法自动把列钉进左侧栏位。
'    此时用本 VBA 宏在本机 MSP 内原生执行即可（VBA 宿主的 TableEditEx
'    不受该 COM 限制）。
'
'  用法：
'    1) 打开由本工具生成的 .mpp 文件；
'    2) 按 Alt+F11 打开 VBA 编辑器 → 插入 → 模块 → 粘贴本文件全文；
'    3) 关闭编辑器，按 Alt+F8 → 选择 AddResponsibilityColumns → 运行。
'    也可直接把本文件拖入 MSP 的「宏」导入。
' ============================================================
Option Explicit

Sub AddResponsibilityColumns()
    Dim tblName As String
    tblName = "责任分工视图"

    On Error Resume Next

    ' 1) 重命名自定义字段（若 Python 已改名则无副作用）
    CustomFieldRename pjText1, "执行单位"
    CustomFieldRename pjText2, "责任人"
    CustomFieldRename pjText3, "责任标识"

    ' 2) 新建自定义表（覆盖同名旧表）
    TableEditEx Name:=tblName, TaskTable:=True, Create:=True, OverwriteExisting:=True

    ' 3) 逐列追加（首列必须是任务名称）
    TableEditEx Name:=tblName, TaskTable:=True, Create:=False, _
                FieldName:="Name", NewFieldName:="Name", _
                Title:="任务名称", Width:=30, ShowInMenu:=True
    TableEditEx Name:=tblName, TaskTable:=True, Create:=False, _
                FieldName:="Text1", NewFieldName:="Text1", _
                Title:="执行单位", Width:=16, ShowInMenu:=True
    TableEditEx Name:=tblName, TaskTable:=True, Create:=False, _
                FieldName:="Text2", NewFieldName:="Text2", _
                Title:="责任人", Width:=16, ShowInMenu:=True
    TableEditEx Name:=tblName, TaskTable:=True, Create:=False, _
                FieldName:="Text3", NewFieldName:="Text3", _
                Title:="责任标识", Width:=18, ShowInMenu:=True

    ' 4) 应用该视图（左侧甘特图即显示三列）
    ViewApplyEx Name:=tblName, SinglePane:=True

    On Error GoTo 0
    MsgBox "已创建并应用「" & tblName & "」：" & vbCrLf & _
           "任务名称 / 执行单位 / 责任人 / 责任标识", vbInformation, "责任分工视图"
End Sub
