using Dapper;
using Microsoft.AspNetCore.Mvc;
using POTMS.Data;
using POTMS.Services;
// Pages/Certificate 命名空间会遮蔽同名实体类型，此处显式取别名
using CertEntity = POTMS.Data.Certificate;

namespace POTMS.Pages.Personnel;

public class ViewPageModel(Db db, Flash flash) : AppPageModel(flash)
{
    public PersonnelFiling Filing { get; private set; } = new();
    public PersonnelInfo? Info { get; private set; }
    public PersonnelFiling? Successor { get; private set; }     // 本记录被哪条新记录替代
    public PersonnelFiling? Predecessor { get; private set; }   // 本记录替代了哪条旧记录
    public List<CertEntity> Certificates { get; private set; } = [];
    public List<TravelDetail> Travels { get; private set; } = [];
    public List<CertIssuance> Issuances { get; private set; } = [];

    public IActionResult OnGet(long id)
    {
        using var cn = db.Open();
        var f = cn.QueryFirstOrDefault<PersonnelFiling>(
            "SELECT * FROM personnel_filing WHERE id=@id", new { id });
        if (f is null) { Flash.Danger("记录不存在。"); return Redirect("/Personnel"); }
        Filing = f;

        if (f.PersonnelInfoId is not null)
            Info = cn.QueryFirstOrDefault<PersonnelInfo>(
                "SELECT * FROM personnel_info WHERE id=@i", new { i = f.PersonnelInfoId });

        // 撤控重报关联链路
        if (f.ReplacedById is not null)
            Successor = cn.QueryFirstOrDefault<PersonnelFiling>(
                "SELECT * FROM personnel_filing WHERE id=@i", new { i = f.ReplacedById });
        Predecessor = cn.QueryFirstOrDefault<PersonnelFiling>(
            "SELECT * FROM personnel_filing WHERE replaced_by_id=@id", new { id });

        Certificates = cn.Query<CertEntity>(
            "SELECT * FROM certificates WHERE personnel_filing_id=@id", new { id }).AsList();
        Travels = cn.Query<TravelDetail>(
            "SELECT * FROM travel_details WHERE personnel_filing_id=@id ORDER BY created_at DESC",
            new { id }).AsList();
        Issuances = cn.Query<CertIssuance>(
            "SELECT * FROM cert_issuance WHERE personnel_filing_id=@id ORDER BY issue_date DESC",
            new { id }).AsList();
        return Page();
    }
}
